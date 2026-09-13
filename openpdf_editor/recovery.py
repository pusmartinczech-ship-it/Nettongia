from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import Any

from PIL import Image

from . import __version__
from .engine import (
    ImageDeletion,
    ImagePlacement,
    ImageRun,
    SignaturePlacement,
    TextEdit,
    TextPlacement,
    TextRun,
)


RECOVERY_FORMAT = "openpdf-editor-recovery"
RECOVERY_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 512 * 1024 * 1024
MAX_ITEMS_PER_KIND = 250_000
_ASSET_MEMBER = re.compile(r"assets/(?:signature|image)-[0-9a-f]{64}\.bin\Z")


class RecoveryCancelled(Exception):
    """Internal signal used when a superseded background write is cancelled."""


@dataclass(frozen=True)
class RecoverySnapshot:
    pdf_bytes: bytes
    edits: tuple[TextEdit, ...]
    inserted_texts: tuple[TextPlacement, ...]
    signatures: tuple[SignaturePlacement, ...]
    inserted_images: tuple[ImagePlacement, ...]
    deleted_images: tuple[ImageDeletion, ...]
    document_path: str | None
    save_target_path: str | None
    current_page: int
    render_scale: float


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_to_json(run: TextRun) -> dict[str, Any]:
    return {
        "key": run.key,
        "page_index": run.page_index,
        "block_index": run.block_index,
        "line_index": run.line_index,
        "span_index": run.span_index,
        "text": run.text,
        "bbox": list(run.bbox),
        "origin": list(run.origin),
        "font_name": run.font_name,
        "font_size": run.font_size,
        "color": run.color,
        "flags": run.flags,
        "direction": list(run.direction),
    }


def _edit_to_json(edit: TextEdit) -> dict[str, Any]:
    return {
        "run": _run_to_json(edit.run),
        "new_text": edit.new_text,
        "font_size": edit.font_size,
        "fit_to_width": edit.fit_to_width,
        "font_family": edit.font_family,
        "bold": edit.bold,
        "italic": edit.italic,
        "underline": edit.underline,
        "color": edit.color,
        "bbox": list(edit.bbox) if edit.bbox is not None else None,
    }


def _text_placement_to_json(item: TextPlacement) -> dict[str, Any]:
    return {
        "key": item.key,
        "page_index": item.page_index,
        "bbox": list(item.bbox),
        "text": item.text,
        "font_family": item.font_family,
        "font_size": item.font_size,
        "bold": item.bold,
        "italic": item.italic,
        "underline": item.underline,
        "color": item.color,
    }


def _image_run_to_json(run: ImageRun) -> dict[str, Any]:
    return {
        "key": run.key,
        "page_index": run.page_index,
        "bbox": list(run.bbox),
        "xref": run.xref,
        "width": run.width,
        "height": run.height,
        "smask": run.smask,
        "rotation_degrees": run.rotation_degrees,
    }


def _asset_reference(prefix: str, data: bytes, assets: dict[str, bytes]) -> dict[str, Any]:
    digest = _sha256(data)
    member = f"assets/{prefix}-{digest}.bin"
    previous = assets.setdefault(member, bytes(data))
    if previous != data:
        raise ValueError("A recovery asset hash collision was detected.")
    return {"member": member, "size": len(data), "sha256": digest}


def _manifest(snapshot: RecoverySnapshot) -> tuple[dict[str, Any], dict[str, bytes]]:
    assets: dict[str, bytes] = {}
    signatures = []
    for item in snapshot.signatures:
        signatures.append(
            {
                "page_index": item.page_index,
                "bbox": list(item.bbox),
                "asset": _asset_reference("signature", item.png_bytes, assets),
                "description": item.description,
                "key": item.key,
                "rotation_degrees": item.rotation_degrees,
            }
        )
    inserted_images = []
    for item in snapshot.inserted_images:
        inserted_images.append(
            {
                "key": item.key,
                "page_index": item.page_index,
                "bbox": list(item.bbox),
                "asset": _asset_reference("image", item.image_bytes, assets),
                "description": item.description,
                "rotation_degrees": item.rotation_degrees,
                "overlay": item.overlay,
            }
        )
    source = bytes(snapshot.pdf_bytes)
    return (
        {
            "format": RECOVERY_FORMAT,
            "schema_version": RECOVERY_SCHEMA_VERSION,
            "application_version": __version__,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "document_path": snapshot.document_path,
            "save_target_path": snapshot.save_target_path,
            "current_page": snapshot.current_page,
            "render_scale": snapshot.render_scale,
            "source": {
                "member": "source.pdf",
                "size": len(source),
                "sha256": _sha256(source),
            },
            "edits": [_edit_to_json(item) for item in snapshot.edits],
            "inserted_texts": [
                _text_placement_to_json(item) for item in snapshot.inserted_texts
            ],
            "signatures": signatures,
            "inserted_images": inserted_images,
            "deleted_images": [
                {
                    "run": _image_run_to_json(item.run),
                    "fill_removed_area": item.fill_removed_area,
                }
                for item in snapshot.deleted_images
            ],
        },
        assets,
    )


def write_recovery_snapshot(
    path: str | Path,
    snapshot: RecoverySnapshot,
    cancel_event: Event | None = None,
) -> int:
    """Write a safe recovery archive and replace the previous copy atomically."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest, assets = _manifest(snapshot)
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError("The recovery manifest is too large.")
    if sum(len(data) for data in assets.values()) > MAX_ASSET_BYTES:
        raise ValueError("The recovery assets are too large.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise RecoveryCancelled()
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            archive.writestr(
                "manifest.json",
                manifest_bytes,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            )
            archive.writestr(
                "source.pdf",
                snapshot.pdf_bytes,
                compress_type=zipfile.ZIP_STORED,
            )
            for member, data in sorted(assets.items()):
                if cancel_event is not None and cancel_event.is_set():
                    raise RecoveryCancelled()
                archive.writestr(member, data, compress_type=zipfile.ZIP_STORED)
        if cancel_event is not None and cancel_event.is_set():
            raise RecoveryCancelled()
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return target.stat().st_size
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Invalid recovery field: {name}.")
    return value


def _sequence(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS_PER_KIND:
        raise ValueError(f"Invalid recovery field: {name}.")
    return value


def _string(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_MANIFEST_BYTES:
        raise ValueError(f"Invalid recovery field: {name}.")
    return value


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    maximum: int = 2_147_483_647,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid recovery field: {name}.")
    if value < minimum or value > maximum:
        raise ValueError(f"Invalid recovery field: {name}.")
    return value


def _number(
    value: Any,
    name: str,
    *,
    minimum: float = -1.0e9,
    maximum: float = 1.0e9,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid recovery field: {name}.")
    converted = float(value)
    if not math.isfinite(converted) or converted < minimum or converted > maximum:
        raise ValueError(f"Invalid recovery field: {name}.")
    return converted


def _boolean(value: Any, name: str, *, nullable: bool = False) -> bool | None:
    if nullable and value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Invalid recovery field: {name}.")
    return value


def _numbers(value: Any, name: str, length: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"Invalid recovery field: {name}.")
    return tuple(_number(item, name) for item in value)


def _optional_bbox(value: Any, name: str) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    result = _numbers(value, name, 4)
    return result[0], result[1], result[2], result[3]


def _text_run_from_json(value: Any) -> TextRun:
    item = _mapping(value, "run")
    bbox = _numbers(item.get("bbox"), "run.bbox", 4)
    origin = _numbers(item.get("origin"), "run.origin", 2)
    direction_value = item.get("direction")
    direction = (
        (1.0, 0.0)
        if direction_value is None
        else _numbers(direction_value, "run.direction", 2)
    )
    direction_length = math.hypot(direction[0], direction[1])
    if direction_length < 1e-7:
        raise ValueError("Invalid recovery field: run.direction.")
    return TextRun(
        key=str(_string(item.get("key"), "run.key")),
        page_index=_integer(item.get("page_index"), "run.page_index"),
        block_index=_integer(item.get("block_index"), "run.block_index"),
        line_index=_integer(item.get("line_index"), "run.line_index"),
        span_index=_integer(item.get("span_index"), "run.span_index"),
        text=str(_string(item.get("text"), "run.text")),
        bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
        origin=(origin[0], origin[1]),
        font_name=str(_string(item.get("font_name"), "run.font_name")),
        font_size=_number(item.get("font_size"), "run.font_size", minimum=0.01),
        color=_integer(item.get("color"), "run.color", maximum=0xFFFFFF),
        flags=_integer(item.get("flags"), "run.flags"),
        direction=(direction[0] / direction_length, direction[1] / direction_length),
    )


def _edit_from_json(value: Any) -> TextEdit:
    item = _mapping(value, "edit")
    family = _string(item.get("font_family"), "edit.font_family", nullable=True)
    color_value = item.get("color")
    color = None if color_value is None else _integer(color_value, "edit.color", maximum=0xFFFFFF)
    return TextEdit(
        run=_text_run_from_json(item.get("run")),
        new_text=str(_string(item.get("new_text"), "edit.new_text")),
        font_size=_number(item.get("font_size"), "edit.font_size", minimum=0.01),
        fit_to_width=bool(_boolean(item.get("fit_to_width"), "edit.fit_to_width")),
        font_family=family,
        bold=_boolean(item.get("bold"), "edit.bold", nullable=True),
        italic=_boolean(item.get("italic"), "edit.italic", nullable=True),
        underline=bool(_boolean(item.get("underline"), "edit.underline")),
        color=color,
        bbox=_optional_bbox(item.get("bbox"), "edit.bbox"),
    )


def _text_placement_from_json(value: Any) -> TextPlacement:
    item = _mapping(value, "inserted_text")
    bbox = _numbers(item.get("bbox"), "inserted_text.bbox", 4)
    return TextPlacement(
        key=str(_string(item.get("key"), "inserted_text.key")),
        page_index=_integer(item.get("page_index"), "inserted_text.page_index"),
        bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
        text=str(_string(item.get("text"), "inserted_text.text")),
        font_family=str(_string(item.get("font_family"), "inserted_text.font_family")),
        font_size=_number(
            item.get("font_size"), "inserted_text.font_size", minimum=0.01
        ),
        bold=bool(_boolean(item.get("bold"), "inserted_text.bold")),
        italic=bool(_boolean(item.get("italic"), "inserted_text.italic")),
        underline=bool(_boolean(item.get("underline"), "inserted_text.underline")),
        color=_integer(item.get("color"), "inserted_text.color", maximum=0xFFFFFF),
    )


def _asset_from_json(
    archive: zipfile.ZipFile,
    value: Any,
    expected_prefix: str,
    cache: dict[str, bytes],
) -> tuple[str, bytes]:
    item = _mapping(value, "asset")
    member = str(_string(item.get("member"), "asset.member"))
    if not _ASSET_MEMBER.fullmatch(member) or not member.startswith(
        f"assets/{expected_prefix}-"
    ):
        raise ValueError("Invalid recovery asset path.")
    expected_size = _integer(
        item.get("size"), "asset.size", maximum=MAX_ASSET_BYTES
    )
    expected_hash = str(_string(item.get("sha256"), "asset.sha256"))
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("Invalid recovery asset checksum.")
    if not member.endswith(f"-{expected_hash}.bin"):
        raise ValueError("Invalid recovery asset checksum path.")
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise ValueError("A recovery asset is missing.") from exc
    if info.compress_type != zipfile.ZIP_STORED or info.file_size != expected_size:
        raise ValueError("Invalid recovery asset metadata.")
    data = cache.get(member)
    if data is None:
        data = archive.read(info)
        cache[member] = data
    if len(data) != expected_size or _sha256(data) != expected_hash:
        raise ValueError("A recovery asset is damaged.")
    return member, data


def _signature_from_json(
    archive: zipfile.ZipFile,
    value: Any,
    cache: dict[str, bytes],
) -> tuple[SignaturePlacement, str]:
    item = _mapping(value, "signature")
    bbox = _numbers(item.get("bbox"), "signature.bbox", 4)
    member, data = _asset_from_json(archive, item.get("asset"), "signature", cache)
    return (
        SignaturePlacement(
            page_index=_integer(item.get("page_index"), "signature.page_index"),
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            png_bytes=data,
            description=str(_string(item.get("description"), "signature.description")),
            key=str(_string(item.get("key"), "signature.key")),
            rotation_degrees=_number(
                item.get("rotation_degrees"), "signature.rotation_degrees"
            ),
        ),
        member,
    )


def _image_placement_from_json(
    archive: zipfile.ZipFile,
    value: Any,
    cache: dict[str, bytes],
) -> tuple[ImagePlacement, str]:
    item = _mapping(value, "inserted_image")
    bbox = _numbers(item.get("bbox"), "inserted_image.bbox", 4)
    member, data = _asset_from_json(archive, item.get("asset"), "image", cache)
    return (
        ImagePlacement(
            key=str(_string(item.get("key"), "inserted_image.key")),
            page_index=_integer(item.get("page_index"), "inserted_image.page_index"),
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            image_bytes=data,
            description=str(
                _string(item.get("description"), "inserted_image.description")
            ),
            rotation_degrees=_number(
                item.get("rotation_degrees", 0.0),
                "inserted_image.rotation_degrees",
            ),
            overlay=_boolean(item.get("overlay", True), "inserted_image.overlay"),
        ),
        member,
    )


def _image_deletion_from_json(value: Any) -> ImageDeletion:
    item = _mapping(value, "deleted_image")
    run = _mapping(item.get("run"), "deleted_image.run")
    bbox = _numbers(run.get("bbox"), "deleted_image.run.bbox", 4)
    return ImageDeletion(
        ImageRun(
            key=str(_string(run.get("key"), "deleted_image.run.key")),
            page_index=_integer(
                run.get("page_index"), "deleted_image.run.page_index"
            ),
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            xref=_integer(run.get("xref"), "deleted_image.run.xref"),
            width=_integer(run.get("width"), "deleted_image.run.width"),
            height=_integer(run.get("height"), "deleted_image.run.height"),
            smask=_integer(run.get("smask", 0), "deleted_image.run.smask"),
            rotation_degrees=_number(
                run.get("rotation_degrees", 0.0),
                "deleted_image.run.rotation_degrees",
            ),
        ),
        fill_removed_area=_boolean(
            item.get("fill_removed_area", True),
            "deleted_image.fill_removed_area",
        ),
    )


def read_recovery_snapshot(path: str | Path) -> RecoverySnapshot:
    """Read and strictly validate an OpenPDF Editor recovery archive."""

    source_path = Path(path)
    try:
        archive = zipfile.ZipFile(source_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("The recovery file is not a valid archive.") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("The recovery archive contains duplicate entries.")
        if len(infos) > MAX_ITEMS_PER_KIND * 2 + 2:
            raise ValueError("The recovery archive contains too many entries.")
        asset_size = sum(
            info.file_size for info in infos if info.filename.startswith("assets/")
        )
        if asset_size > MAX_ASSET_BYTES:
            raise ValueError("The recovery assets are too large.")
        try:
            manifest_info = archive.getinfo("manifest.json")
        except KeyError as exc:
            raise ValueError("The recovery manifest is missing.") from exc
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("The recovery manifest is too large.")
        try:
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The recovery manifest is damaged.") from exc
        root = _mapping(manifest, "manifest")
        if root.get("format") != RECOVERY_FORMAT:
            raise ValueError("This is not an OpenPDF Editor recovery file.")
        if root.get("schema_version") != RECOVERY_SCHEMA_VERSION:
            raise ValueError("This recovery format version is not supported.")

        source_descriptor = _mapping(root.get("source"), "source")
        if source_descriptor.get("member") != "source.pdf":
            raise ValueError("Invalid recovery PDF path.")
        source_size = _integer(
            source_descriptor.get("size"), "source.size", maximum=2_147_483_647
        )
        source_hash = str(_string(source_descriptor.get("sha256"), "source.sha256"))
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError("Invalid recovery PDF checksum.")
        try:
            source_info = archive.getinfo("source.pdf")
        except KeyError as exc:
            raise ValueError("The recovery PDF is missing.") from exc
        if source_info.compress_type != zipfile.ZIP_STORED or source_info.file_size != source_size:
            raise ValueError("Invalid recovery PDF metadata.")
        pdf_bytes = archive.read(source_info)
        if len(pdf_bytes) != source_size or _sha256(pdf_bytes) != source_hash:
            raise ValueError("The recovery PDF is damaged.")
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("The recovery source is not a PDF.")

        edits = tuple(_edit_from_json(item) for item in _sequence(root.get("edits"), "edits"))
        edit_keys = [item.run.key for item in edits]
        if len(edit_keys) != len(set(edit_keys)):
            raise ValueError("The recovery data contains duplicate text edits.")
        inserted_texts = tuple(
            _text_placement_from_json(item)
            for item in _sequence(root.get("inserted_texts"), "inserted_texts")
        )
        asset_cache: dict[str, bytes] = {}
        signature_values = [
            _signature_from_json(archive, item, asset_cache)
            for item in _sequence(root.get("signatures"), "signatures")
        ]
        signatures = tuple(item for item, _ in signature_values)
        image_values = [
            _image_placement_from_json(archive, item, asset_cache)
            for item in _sequence(root.get("inserted_images"), "inserted_images")
        ]
        inserted_images = tuple(item for item, _ in image_values)
        deleted_images = tuple(
            _image_deletion_from_json(item)
            for item in _sequence(root.get("deleted_images"), "deleted_images")
        )
        expected_members = {"manifest.json", "source.pdf"}
        expected_members.update(member for _, member in signature_values)
        expected_members.update(member for _, member in image_values)
        if set(names) != expected_members:
            raise ValueError("The recovery archive contains unexpected entries.")
        return RecoverySnapshot(
            pdf_bytes=pdf_bytes,
            edits=edits,
            inserted_texts=inserted_texts,
            signatures=signatures,
            inserted_images=inserted_images,
            deleted_images=deleted_images,
            document_path=_string(
                root.get("document_path"), "document_path", nullable=True
            ),
            save_target_path=_string(
                root.get("save_target_path"), "save_target_path", nullable=True
            ),
            current_page=_integer(root.get("current_page"), "current_page"),
            render_scale=_number(
                root.get("render_scale"), "render_scale", minimum=0.01, maximum=100.0
            ),
        )


def validate_recovery_pages(snapshot: RecoverySnapshot, page_count: int) -> None:
    if page_count < 1:
        raise ValueError("The recovered PDF has no pages.")
    page_indices = [snapshot.current_page]
    page_indices.extend(item.run.page_index for item in snapshot.edits)
    page_indices.extend(item.page_index for item in snapshot.inserted_texts)
    page_indices.extend(item.page_index for item in snapshot.signatures)
    page_indices.extend(item.page_index for item in snapshot.inserted_images)
    page_indices.extend(item.run.page_index for item in snapshot.deleted_images)
    if any(index >= page_count for index in page_indices):
        raise ValueError("The recovery data refers to a page that does not exist.")


def validate_recovery_assets(snapshot: RecoverySnapshot) -> None:
    """Reject damaged or implausibly large image payloads before UI activation."""

    assets = [
        ("signature", item.png_bytes, True) for item in snapshot.signatures
    ]
    assets.extend(
        ("image", item.image_bytes, False) for item in snapshot.inserted_images
    )
    for kind, data, require_png in assets:
        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                image_format = image.format
                if width < 1 or height < 1 or width * height > 250_000_000:
                    raise ValueError(f"The recovered {kind} has invalid dimensions.")
                if require_png and image_format != "PNG":
                    raise ValueError("A recovered signature is not a PNG image.")
                image.verify()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"A recovered {kind} is not a valid image.") from exc


def remove_recovery_file(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def quarantine_recovery_file(path: str | Path) -> Path | None:
    source = Path(path)
    if not source.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-2", "-3", "-4", "-5"):
        target = source.with_name(f"{source.name}.damaged-{stamp}{suffix}")
        if target.exists():
            continue
        try:
            os.replace(source, target)
            return target
        except OSError:
            return None
    return None
