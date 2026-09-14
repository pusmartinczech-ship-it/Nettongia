from pathlib import Path


project_root = Path(SPEC).resolve().parent
datas = [
    (str(project_root / "assets"), "assets"),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "NOTICE.txt"), "."),
    (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
]
ocr_root = project_root / "vendor" / "ocr"
if ocr_root.is_dir():
    datas.append((str(ocr_root), "ocr"))

a = Analysis(
    [str(project_root / "run_editor.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtPrintSupport",
        "PySide6.QtSvg",
        "PIL.Image",
        "openpdf_editor.inspection_worker",
        "openpdf_editor.ocr_worker",
        "openpdf_editor.portable_ocr_acceptance",
        "openpdf_editor.tile_worker",
        "openpdf_editor.write_worker",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NettongiaPDFEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "nettongia.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NettongiaPDFEditor",
)
