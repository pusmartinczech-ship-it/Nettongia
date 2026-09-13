import hashlib
import json
from pathlib import Path

from openpdf_editor import runtime


ROOT = Path(__file__).resolve().parents[1]


def test_windows_distribution_files_are_present_and_spec_is_valid_python() -> None:
    required = (
        "OpenPDFEditor.spec",
        "requirements-windows.lock",
        "tools/build_windows.ps1",
        "tools/collect_licenses.py",
        "tools/fetch_ocr_assets.py",
        "tools/verify_ocr_bundle.py",
        "openpdf_editor/portable_ocr_acceptance.py",
        "installer/OpenPDFEditor.iss",
        ".github/workflows/windows-build.yml",
        "DEPENDENCY_POLICY.md",
        "THIRD_PARTY_NOTICES.md",
        "SIGNING.md",
    )
    assert all((ROOT / name).is_file() for name in required)
    spec = (ROOT / "OpenPDFEditor.spec").read_text(encoding="utf-8")
    compile(spec, "OpenPDFEditor.spec", "exec")

    build_script = (ROOT / "tools" / "build_windows.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(
        encoding="utf-8"
    )
    assert "Invoke-WebRequest" not in build_script
    assert "TesseractRoot" not in build_script
    assert '"vendor"' in build_script
    assert "choco install tesseract" not in workflow
    assert "python ./tools/fetch_ocr_assets.py" in workflow
    assert runtime.verify_bundled_ocr(ROOT / "vendor" / "ocr")


def test_packaged_runtime_prefers_bundled_tessdata(tmp_path: Path, monkeypatch) -> None:
    tessdata = tmp_path / "ocr" / "tessdata"
    tessdata.mkdir(parents=True)
    files = {}
    for language in runtime.REQUIRED_OCR_LANGUAGES:
        relative = f"tessdata/{language}.traineddata"
        payload = f"model-{language}".encode()
        (tmp_path / "ocr" / relative).write_bytes(payload)
        files[relative] = hashlib.sha256(payload).hexdigest()
    (tmp_path / "ocr" / "SHA256SUMS.json").write_text(
        json.dumps({"format": "openpdf-ocr-assets-v1", "files": files}),
        encoding="utf-8",
    )
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(runtime, "resource_root", lambda: tmp_path)

    runtime.configure_packaged_runtime()

    assert Path(runtime.os.environ["TESSDATA_PREFIX"]) == tessdata


def test_windows_runtime_stages_unicode_tessdata_in_verified_ascii_cache(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "balíček s diakritikou" / "ocr"
    tessdata = source / "tessdata"
    tessdata.mkdir(parents=True)
    files = {}
    for language in runtime.REQUIRED_OCR_LANGUAGES:
        relative = f"tessdata/{language}.traineddata"
        payload = f"model-{language}".encode()
        (source / relative).write_bytes(payload)
        files[relative] = hashlib.sha256(payload).hexdigest()
    (source / "SHA256SUMS.json").write_text(
        json.dumps({"format": "openpdf-ocr-assets-v1", "files": files}),
        encoding="utf-8",
    )
    ascii_temp = tmp_path / "ascii-temp"
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(ascii_temp))
    monkeypatch.setattr(runtime, "resource_root", lambda: source.parent)

    resolved = runtime.bundled_tessdata_path(verify=True)

    assert resolved is not None
    assert "balíček s diakritikou" not in str(resolved)
    assert runtime.verify_bundled_ocr(resolved.parent)


def test_bundled_ocr_manifest_rejects_modified_model(tmp_path: Path) -> None:
    source = ROOT / "vendor" / "ocr"
    destination = tmp_path / "ocr"
    destination.mkdir()
    (destination / "tessdata").mkdir()
    (destination / "SHA256SUMS.json").write_bytes(
        (source / "SHA256SUMS.json").read_bytes()
    )
    for path in (source / "tessdata").glob("*.traineddata"):
        (destination / "tessdata" / path.name).write_bytes(path.read_bytes())
    (destination / "LICENSE-tessdata.txt").write_bytes(
        (source / "LICENSE-tessdata.txt").read_bytes()
    )

    assert runtime.verify_bundled_ocr(destination)
    with (destination / "tessdata" / "ces.traineddata").open("ab") as stream:
        stream.write(b"damaged")
    assert not runtime.verify_bundled_ocr(destination)


def test_bundled_ocr_manifest_rejects_missing_model(tmp_path: Path) -> None:
    source = ROOT / "vendor" / "ocr"
    destination = tmp_path / "OCR balíček s diakritikou"
    import shutil

    shutil.copytree(source, destination)
    (destination / "tessdata" / "slk.traineddata").unlink()

    assert runtime.bundled_tessdata_path() is not None
    assert not runtime.verify_bundled_ocr(destination)


def test_windows_build_defines_portable_size_budgets_and_clean_ocr_gate() -> None:
    script = (ROOT / "tools" / "build_windows.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(
        encoding="utf-8"
    )
    assert "32MB" in script
    assert "850MB" in script
    assert "400MB" in script
    assert "distribution-size.json" in script
    assert "portable.zip" in script
    assert "Čistý OCR balíček žluťoučký kůň" in workflow
    assert "Get-Command tesseract.exe" in workflow
    assert "--ocr-acceptance" in workflow
    assert "Start-Process -FilePath $executable.FullName" in workflow
    assert "isolated_ocr_execution" in workflow
    assert "process_cancellation" in workflow
