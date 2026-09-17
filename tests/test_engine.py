import os
import math
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageChops, ImageDraw

from openpdf_editor.engine import (
    ImageDeletion,
    ImagePlacement,
    PdfEngine,
    PdfInvalidPasswordError,
    PdfPasswordRequiredError,
    SignaturePlacement,
    TextEdit,
    TextPlacement,
    _builtin_pdf_font_name,
)


SAMPLES = Path(os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload"))


def _encrypted_pdf(password: str = "open-sesame") -> bytes:
    document = fitz.open()
    page = document.new_page(width=420, height=300)
    page.insert_text((60, 80), "Protected document", fontsize=18)
    try:
        return document.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw=password,
        )
    finally:
        document.close()


def test_styled_builtin_font_fallbacks() -> None:
    assert _builtin_pdf_font_name("TimesNewRomanPS-BoldMT", True, False) == "tibo"
    assert _builtin_pdf_font_name("Arial-BoldItalicMT", True, True) == "hebi"
    assert _builtin_pdf_font_name("Courier New", False, True) == "coit"


def test_blank_document_creation() -> None:
    payload = PdfEngine.blank_document_bytes(595.28, 841.89, 3)
    with fitz.open(stream=payload, filetype="pdf") as document:
        assert document.page_count == 3
        assert document[0].rect.width == pytest.approx(595.28, abs=0.1)
        assert document[0].rect.height == pytest.approx(841.89, abs=0.1)
        assert document.metadata["creator"] == "Nettongia PDF Editor"


def test_password_protected_pdf_can_be_opened_and_edited() -> None:
    payload = _encrypted_pdf()
    engine = PdfEngine()

    with pytest.raises(PdfPasswordRequiredError):
        engine.load_bytes(payload)
    with pytest.raises(PdfInvalidPasswordError):
        engine.load_bytes(payload, password="wrong")

    engine.load_bytes(payload, password="open-sesame")
    assert engine.was_encrypted
    assert "Protected document" in engine.text_runs(0)[0].text
    rendered, width, height, _stride = engine.render_page(0, 1.0)
    assert rendered and width == 420 and height == 300

    composed = engine.compose_bytes()
    with fitz.open(stream=composed, filetype="pdf") as document:
        assert not document.needs_pass
        assert "Protected document" in document[0].get_text()


def test_zero_page_pdf_is_rejected_during_load(monkeypatch) -> None:
    class EmptyDocument:
        needs_pass = False
        page_count = 0

        def close(self) -> None:
            pass

    monkeypatch.setattr("openpdf_editor.engine.pymupdf.open", lambda **_kwargs: EmptyDocument())
    engine = PdfEngine()

    with pytest.raises(ValueError, match="at least one page"):
        engine.load_bytes(b"synthetic empty PDF")
    assert not engine.is_open


def test_large_page_render_scale_is_capped() -> None:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(3370.4, 2383.94))

    maximum = engine.max_render_scale(0)

    assert maximum < 4.0
    assert maximum == pytest.approx((32_000_000 / (3370.4 * 2383.94)) ** 0.5, rel=1e-6)


def test_page_rotation_updates_visible_geometry_and_keeps_new_text_upright() -> None:
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((50, 60), "ORIGINAL", fontsize=20)
    payload = document.tobytes()
    document.close()

    engine = PdfEngine()
    engine.load_bytes(payload)
    engine.load_bytes(engine.bytes_with_page_rotated(0, 1))

    assert engine._source[0].rotation == 90
    assert engine.page_rect(0).width == pytest.approx(300)
    assert engine.page_rect(0).height == pytest.approx(400)
    original = next(run for run in engine.text_runs(0) if run.text == "ORIGINAL")
    assert original.direction == pytest.approx((0.0, 1.0), abs=1e-6)
    assert 0 <= original.bbox[0] < original.bbox[2] <= 300
    assert 0 <= original.bbox[1] < original.bbox[3] <= 400

    replaced = engine.compose_bytes(
        edits=[TextEdit(original, "CHANGED", original.font_size)]
    )
    engine.load_bytes(replaced)
    changed = next(run for run in engine.text_runs(0) if run.text == "CHANGED")
    assert changed.direction == pytest.approx((0.0, 1.0), abs=1e-6)

    composed = engine.compose_bytes(
        inserted_texts=[
            TextPlacement("upright", 0, (20, 20, 180, 60), "UPRIGHT")
        ]
    )
    engine.load_bytes(composed)
    inserted = next(run for run in engine.text_runs(0) if run.text == "UPRIGHT")
    assert inserted.direction == pytest.approx((1.0, 0.0), abs=1e-6)
    assert inserted.bbox[0] == pytest.approx(20, abs=1)
    assert 20 <= inserted.bbox[1] <= 35

    engine.load_bytes(engine.bytes_with_page_rotated(0, -1))
    assert engine._source[0].rotation == 0
    assert engine.page_rect(0).width == pytest.approx(400)
    assert engine.page_rect(0).height == pytest.approx(300)


def test_atomic_save_keeps_existing_target_when_save_fails(tmp_path: Path) -> None:
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"original PDF")

    class FailingDocument:
        def save(self, path: str, **_options: object) -> None:
            Path(path).write_bytes(b"truncated output")
            raise OSError("simulated save failure")

    with pytest.raises(OSError, match="simulated save failure"):
        PdfEngine._save_document_atomic(FailingDocument(), target)

    assert target.read_bytes() == b"original PDF"
    assert not list(tmp_path.glob(".existing.pdf.*.tmp"))


def test_regular_save_uses_fast_safe_compaction(monkeypatch, tmp_path: Path) -> None:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))

    class FakeDocument:
        closed = False

        def close(self) -> None:
            self.closed = True

    document = FakeDocument()
    options = {}
    monkeypatch.setattr(engine, "build_document", lambda *_args, **_kwargs: document)

    def capture_save(actual_document, _path, **actual_options) -> None:
        assert actual_document is document
        options.update(actual_options)

    monkeypatch.setattr(engine, "_save_document_atomic", capture_save)
    engine.save(tmp_path / "fast.pdf", [])

    assert options["garbage"] == 2
    assert options["clean"] is False
    assert options["deflate"] is True
    assert document.closed


def test_fast_save_removes_replaced_text_from_pdf_streams(tmp_path: Path) -> None:
    original = "SECRET_ORIGINAL_TOKEN_7391"
    source = fitz.open()
    page = source.new_page(width=420, height=300)
    page.insert_text((50, 90), original, fontsize=16)
    payload = source.tobytes(deflate=False)
    source.close()

    engine = PdfEngine()
    engine.load_bytes(payload)
    run = next(item for item in engine.text_runs(0) if item.text == original)
    output = tmp_path / "physically-replaced.pdf"
    engine.save(output, [TextEdit(run, "PUBLIC REPLACEMENT", run.font_size)])

    with fitz.open(output) as document:
        assert original not in document[0].get_text()
        assert "PUBLIC REPLACEMENT" in document[0].get_text()
        decoded_streams = b"".join(
            document.xref_stream(xref) or b""
            for xref in range(1, document.xref_length())
        )
    assert original.encode("ascii") not in decoded_streams


def test_unmodified_page_render_uses_open_document(monkeypatch) -> None:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))

    def unexpected_rebuild(*args, **kwargs):
        pytest.fail("An unmodified page must render without rebuilding the PDF.")

    monkeypatch.setattr(engine, "build_document", unexpected_rebuild)
    samples, width, height, stride = engine.render_page(0, 0.5)

    assert samples
    assert width == 210
    assert height == 150
    assert stride >= width * 3


def test_inserted_text_box_is_real_pdf_text(tmp_path: Path) -> None:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    placement = TextPlacement(
        key="new-text",
        page_index=0,
        bbox=(50, 55, 360, 145),
        text="NEW DIRECT TEXT\nSecond line",
        font_family="DejaVu Sans",
        font_size=18,
        bold=True,
        italic=False,
        underline=True,
        color=0x174A8B,
    )
    output = tmp_path / "inserted_text.pdf"
    engine.save(output, [], inserted_texts=[placement])

    with fitz.open(output) as document:
        text = document[0].get_text()
        assert "NEW DIRECT TEXT" in text
        assert "Second line" in text
        assert document[0].search_for("NEW DIRECT TEXT")


def test_existing_text_can_move_and_resize(tmp_path: Path) -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    engine = PdfEngine()
    engine.open(SAMPLES / "Test_Word_PDF.pdf")
    run = next(run for run in engine.text_runs(0) if "Článek" in run.text)
    moved_bbox = (
        run.bbox[0] + 90,
        run.bbox[1] + 35,
        run.bbox[2] + 180,
        run.bbox[3] + 50,
    )
    edit = TextEdit(
        run=run,
        new_text="MOVED TEXT",
        font_size=14,
        font_family="DejaVu Sans",
        bold=True,
        bbox=moved_bbox,
    )
    output = tmp_path / "moved_text.pdf"
    engine.save(output, [edit])

    with fitz.open(output) as document:
        hits = document[0].search_for("MOVED TEXT")
        assert hits
        assert hits[0].x0 == pytest.approx(moved_bbox[0], abs=2.0)
        assert run.text not in document[0].get_text()


def test_supplied_pdf_types() -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    engine = PdfEngine()

    engine.open(SAMPLES / "Test_Word_PDF.pdf")
    assert engine.page_count == 1
    assert engine.page_has_editable_text(0)

    engine.open(SAMPLES / "KS_Teil_3_2_04_ROB-KUKA_KL.pdf")
    assert engine.page_count == 30
    assert engine.page_has_editable_text(0)

    engine.open(SAMPLES / "0015_001.pdf")
    assert engine.page_count == 1
    assert not engine.page_has_editable_text(0)


def test_replacement_removes_original_content(tmp_path: Path) -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    engine = PdfEngine()
    engine.open(SAMPLES / "Test_Word_PDF.pdf")
    run = next(run for run in engine.text_runs(0) if "Dozorčí rada" in run.text)
    replacement = "EDITED TEXT"
    output = tmp_path / "edited.pdf"
    engine.save(output, [TextEdit(run, replacement, run.font_size, True)])

    with fitz.open(output) as document:
        text = document[0].get_text()
        assert replacement in text
        assert run.text not in text


@pytest.mark.parametrize("rotation", [90, 270, 33])
def test_rotated_text_keeps_its_direction_after_edit(
    tmp_path: Path,
    rotation: int,
) -> None:
    source = fitz.open()
    page = source.new_page(width=420, height=420)
    origin = fitz.Point(210, 210)
    page.insert_text(
        origin,
        "VERTICAL SOURCE",
        fontsize=15,
        rotate=rotation if rotation != 33 else 0,
        morph=None if rotation != 33 else (origin, fitz.Matrix(rotation)),
    )
    payload = source.tobytes()
    source.close()

    engine = PdfEngine()
    engine.load_bytes(payload)
    run = next(item for item in engine.text_runs(0) if item.text == "VERTICAL SOURCE")
    expected = (math.cos(math.radians(rotation)), -math.sin(math.radians(rotation)))
    assert run.direction == pytest.approx(expected, abs=1e-4)

    output = tmp_path / f"rotated-{rotation}.pdf"
    engine.save(
        output,
        [TextEdit(run, "EDITED DIRECTION", run.font_size, fit_to_width=True)],
    )

    with fitz.open(output) as document:
        edited_line = next(
            line
            for block in document[0].get_text("dict", sort=False)["blocks"]
            if block.get("type") == 0
            for line in block.get("lines", [])
            if any(span.get("text") == "EDITED DIRECTION" for span in line.get("spans", []))
        )
        assert edited_line["dir"] == pytest.approx(expected, abs=1e-4)


def test_formatting_and_visual_signature(tmp_path: Path) -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    engine = PdfEngine()
    engine.open(SAMPLES / "Test_Word_PDF.pdf")
    run = next(run for run in engine.text_runs(0) if "Článek" in run.text)

    signature_image = Image.new("RGBA", (500, 140), (255, 255, 255, 0))
    drawing = ImageDraw.Draw(signature_image)
    drawing.line([(20, 105), (120, 25), (210, 115), (300, 30), (475, 90)], fill=(0, 0, 0, 255), width=8)
    payload = BytesIO()
    signature_image.save(payload, format="PNG")

    edit = TextEdit(
        run=run,
        new_text="FORMATTED HEADING",
        font_size=run.font_size,
        fit_to_width=True,
        font_family="DejaVu Sans",
        bold=True,
        italic=True,
        underline=True,
        color=0xA00000,
    )
    signature = SignaturePlacement(
        0,
        (330, 650, 510, 745),
        payload.getvalue(),
        rotation_degrees=27.0,
    )
    output = tmp_path / "formatted_and_signed.pdf"
    engine.save(output, [edit], [signature])

    with fitz.open(output) as document:
        page = document[0]
        assert "FORMATTED HEADING" in page.get_text()
        assert page.get_images(full=True)
        assert page.get_drawings()


def test_signature_rotation_uses_original_transparent_image() -> None:
    source = Image.new("RGBA", (600, 120), (255, 255, 255, 0))
    drawing = ImageDraw.Draw(source)
    drawing.line((20, 60, 580, 60), fill=(0, 0, 0, 255), width=12)
    payload = BytesIO()
    source.save(payload, format="PNG")
    original = payload.getvalue()
    signature = SignaturePlacement(
        0,
        (200, 500, 420, 650),
        original,
        key="rotated-signature",
        rotation_degrees=32.0,
    )

    rotated = PdfEngine._rotated_signature_payload(signature)
    rotated_image = Image.open(BytesIO(rotated))
    original_image = Image.open(BytesIO(signature.png_bytes))

    assert rotated != original
    assert rotated_image.height > original_image.height * 3
    assert original_image.size == (600, 120)


def test_page_management() -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    engine = PdfEngine()
    engine.open(SAMPLES / "Test_Word_PDF.pdf")

    with_blank = engine.bytes_with_blank_page(0)
    engine.load_bytes(with_blank)
    assert engine.page_count == 2
    assert not engine.page_has_editable_text(1)

    without_blank = engine.bytes_without_page(1)
    engine.load_bytes(without_blank)
    assert engine.page_count == 1

    with_import, inserted = engine.bytes_with_pdf_inserted(0, SAMPLES / "Test_Word_PDF.pdf")
    engine.load_bytes(with_import)
    assert inserted == 1
    assert engine.page_count == 2
    assert engine.page_has_editable_text(1)


def test_page_move_preserves_content_and_outline_destination() -> None:
    document = fitz.open()
    for label in ("FIRST", "SECOND", "THIRD"):
        page = document.new_page(width=420, height=300)
        page.insert_text((60, 100), label, fontsize=24)
    document.set_toc([[1, "First bookmark", 1]])
    source = document.tobytes()
    document.close()

    engine = PdfEngine()
    engine.load_bytes(source)
    moved = engine.bytes_with_page_moved(0, 2)

    with fitz.open(stream=moved, filetype="pdf") as result:
        assert [page.get_text().strip() for page in result] == ["SECOND", "THIRD", "FIRST"]
        assert result.get_toc()[0][2] == 3


def test_password_protected_pages_can_be_imported(tmp_path: Path) -> None:
    protected = tmp_path / "protected-import.pdf"
    protected.write_bytes(_encrypted_pdf("import-password"))
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))

    with pytest.raises(PdfPasswordRequiredError):
        engine.bytes_with_pdf_inserted(0, protected)
    with pytest.raises(PdfInvalidPasswordError):
        engine.bytes_with_pdf_inserted(0, protected, password="wrong")

    combined, inserted = engine.bytes_with_pdf_inserted(
        0,
        protected,
        password="import-password",
    )
    with fitz.open(stream=combined, filetype="pdf") as document:
        assert inserted == 1
        assert document.page_count == 2
        assert "Protected document" in document[1].get_text()


def test_image_insertion_and_deletion(tmp_path: Path) -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    image = Image.new("RGB", (320, 180), (30, 125, 210))
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((25, 25, 295, 155), outline=(255, 255, 255), width=8)
    payload = BytesIO()
    image.save(payload, format="PNG")

    engine = PdfEngine()
    engine.open(SAMPLES / "Test_Word_PDF.pdf")
    placement = ImagePlacement("test-image", 0, (300, 600, 500, 712.5), payload.getvalue())
    inserted_output = tmp_path / "image_inserted.pdf"
    engine.save(inserted_output, [], [], [placement])
    with fitz.open(inserted_output) as document:
        assert document[0].get_image_info(xrefs=True)

    engine.open(SAMPLES / "0015_001.pdf")
    source_image = max(
        engine.image_runs(0),
        key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]),
    )
    deleted_output = tmp_path / "image_deleted.pdf"
    engine.save(deleted_output, [], [], [], [ImageDeletion(source_image)])
    with fitz.open(deleted_output) as document:
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(0.2, 0.2), alpha=False)
        dark_samples = sum(value < 235 for value in pixmap.samples)
        assert dark_samples < len(pixmap.samples) * 0.03


def test_promoting_original_image_is_pixel_identical_before_transform() -> None:
    image = Image.new("RGBA", (240, 100), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((0, 0, 70, 99), fill="red")
    drawing.rectangle((70, 0, 239, 99), fill="blue")
    payload = BytesIO()
    image.save(payload, format="PNG")
    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_image(
        fitz.Rect(40, 60, 280, 160),
        stream=payload.getvalue(),
        rotate=90,
        overlay=False,
    )
    page.insert_text((80, 110), "TEXT ABOVE", fontsize=20, color=(1, 1, 1))
    source = document.tobytes()
    document.close()

    engine = PdfEngine()
    engine.load_bytes(source)
    run = engine.image_runs(0)[0]
    replacement = ImagePlacement(
        "editable-source",
        0,
        run.bbox,
        engine.extract_image_payload(run),
        rotation_degrees=run.rotation_degrees,
        overlay=False,
    )
    promoted = engine.compose_bytes(
        inserted_images=[replacement],
        deleted_images=[ImageDeletion(run, fill_removed_area=False)],
    )

    def rendered(data: bytes) -> Image.Image:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    assert ImageChops.difference(rendered(source), rendered(promoted)).getbbox() is None


def test_original_jpeg_stream_and_quarter_turn_are_preserved_without_transcoding() -> None:
    image = Image.new("RGB", (260, 110), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((0, 0, 84, 109), fill=(220, 30, 35))
    drawing.rectangle((85, 0, 259, 109), fill=(20, 80, 220))
    payload = BytesIO()
    image.save(payload, format="JPEG", quality=91, subsampling=0)
    original_jpeg = payload.getvalue()

    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_image(
        fitz.Rect(80, 55, 330, 190),
        stream=original_jpeg,
        rotate=90,
        overlay=False,
    )
    source = document.tobytes()
    document.close()

    engine = PdfEngine()
    engine.load_bytes(source)
    run = engine.image_runs(0)[0]
    extracted = engine.extract_image_payload(run)
    assert extracted == original_jpeg
    assert extracted.startswith(b"\xff\xd8")

    promoted = engine.compose_bytes(
        inserted_images=[
            ImagePlacement(
                "editable-jpeg",
                0,
                run.bbox,
                extracted,
                rotation_degrees=run.rotation_degrees,
                overlay=False,
            )
        ],
        deleted_images=[ImageDeletion(run, fill_removed_area=False)],
    )

    def rendered(data: bytes) -> bytes:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            return bytes(
                pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).samples
            )

    assert rendered(promoted) == rendered(source)


def test_strong_compression_produces_valid_pdf(tmp_path: Path) -> None:
    if not SAMPLES.exists():
        pytest.skip("Set OPENPDF_TEST_SAMPLES to the folder containing the supplied PDF fixtures.")
    engine = PdfEngine()
    engine.open(SAMPLES / "0015_001.pdf")
    output = tmp_path / "compressed.pdf"
    result = engine.save_compressed(output, "strong")
    with fitz.open(output) as document:
        assert document.page_count == 1
        assert document[0].rect.width > 0
    assert result.output_size == output.stat().st_size
    assert result.recompressed_images >= 1


def test_failed_post_save_validation_preserves_existing_target(
    tmp_path: Path, monkeypatch
) -> None:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    target = tmp_path / "existing.pdf"
    original = b"existing target must survive"
    target.write_bytes(original)

    def fail_validation(*_args, **_kwargs) -> None:
        raise ValueError("simulated validation failure")

    monkeypatch.setattr(
        PdfEngine,
        "_validate_saved_pdf",
        staticmethod(fail_validation),
    )

    with pytest.raises(ValueError, match="simulated validation failure"):
        engine.save(target, [])

    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".existing.pdf.*.tmp"))
