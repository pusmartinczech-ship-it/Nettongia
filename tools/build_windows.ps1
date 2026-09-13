param([switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This build must run on Windows."
}

$Python = Join-Path $ProjectRoot ".venv-build\Scripts\python.exe"
if (-not (Test-Path $Python)) { py -3.12 -m venv .venv-build }
& $Python -m pip install --upgrade "pip==26.0.1"
& $Python -m pip install -r requirements-windows.lock
& $Python -m pip check
& $Python -m pip freeze --all | Set-Content -Encoding utf8 BUILD_ENVIRONMENT.txt

$OcrRoot = Join-Path $ProjectRoot "vendor\ocr"
& $Python tools\verify_ocr_bundle.py $OcrRoot
if ($LASTEXITCODE -ne 0) {
    throw "The checked-in offline OCR bundle is missing or damaged."
}

Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
& $Python -m PyInstaller --noconfirm --clean OpenPDFEditor.spec

$AppDirectory = Join-Path $ProjectRoot "dist\OpenPDFEditor"
& $Python tools\collect_licenses.py (Join-Path $AppDirectory "licenses")
Copy-Item BUILD_ENVIRONMENT.txt $AppDirectory

$SelfTest = Join-Path $ProjectRoot "dist\self-test.json"
& (Join-Path $AppDirectory "OpenPDFEditor.exe") --self-test $SelfTest
if ($LASTEXITCODE -ne 0) { throw "The packaged application self-test failed." }
$Result = Get-Content $SelfTest -Raw | ConvertFrom-Json
if ($Result.status -ne "passed") { throw "The packaged application self-test did not pass." }
if ((-not $Result.checks.ocr_ready) -or (-not $Result.checks.ocr_assets_verified)) {
    throw "The packaged application cannot see its bundled OCR languages."
}

$Version = & $Python -c "from openpdf_editor import __version__; print(__version__)"
$SourceStage = Join-Path $ProjectRoot "dist\source-stage"
Remove-Item -Recurse -Force $SourceStage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $SourceStage | Out-Null
$SourceItems = @(
    ".github", "assets", "installer", "openpdf_editor", "tests", "tools", "vendor",
    "CHANGELOG.md", "DEVELOPMENT_PROGRESS.md", "LICENSE", "NOTICE.txt",
    "OpenPDFEditor.spec", "README.md", "requirements.txt", "requirements-dev.txt",
    "requirements-windows.lock", "run_editor.py", "THIRD_PARTY_NOTICES.md"
)
foreach ($Item in $SourceItems) {
    if (Test-Path $Item) { Copy-Item $Item $SourceStage -Recurse -Force }
}
$SourceArchive = Join-Path $AppDirectory "OpenPDF_Editor_$Version-source.zip"
Compress-Archive -Path (Join-Path $SourceStage "*") -DestinationPath $SourceArchive -Force
Remove-Item -Recurse -Force $SourceStage

$OcrBytes = (Get-ChildItem (Join-Path $AppDirectory "ocr") -File -Recurse |
    Measure-Object -Property Length -Sum).Sum
$DirectoryBytes = (Get-ChildItem $AppDirectory -File -Recurse |
    Measure-Object -Property Length -Sum).Sum
$MaxOcrBytes = 32MB
$MaxDirectoryBytes = 850MB
if ($OcrBytes -gt $MaxOcrBytes) {
    throw "Bundled OCR data exceeds the 32 MiB release budget."
}
if ($DirectoryBytes -gt $MaxDirectoryBytes) {
    throw "Portable application exceeds the 850 MiB unpacked release budget."
}

$PortableArchive = Join-Path $ProjectRoot "dist\OpenPDF_Editor_$Version-portable.zip"
Compress-Archive -Path $AppDirectory -DestinationPath $PortableArchive -Force
$PortableBytes = (Get-Item $PortableArchive).Length
$MaxPortableBytes = 400MB
if ($PortableBytes -gt $MaxPortableBytes) {
    throw "Portable ZIP exceeds the 400 MiB release budget."
}
$SizeReport = [ordered]@{
    format = "openpdf-distribution-size-v1"
    version = $Version
    unpacked_bytes = [int64]$DirectoryBytes
    portable_zip_bytes = [int64]$PortableBytes
    ocr_assets_bytes = [int64]$OcrBytes
    budgets = [ordered]@{
        unpacked_bytes = [int64]$MaxDirectoryBytes
        portable_zip_bytes = [int64]$MaxPortableBytes
        ocr_assets_bytes = [int64]$MaxOcrBytes
    }
}
$SizeReport | ConvertTo-Json -Depth 3 |
    Set-Content -Encoding utf8 (Join-Path $ProjectRoot "dist\distribution-size.json")

if (-not $SkipInstaller) {
    $IsccCandidates = @(
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { throw "Inno Setup 6 was not found." }
    $env:OPENPDF_VERSION = $Version
    & $Iscc installer\OpenPDFEditor.iss
}

Get-FileHash -Algorithm SHA256 (Join-Path $AppDirectory "OpenPDFEditor.exe")
Get-FileHash -Algorithm SHA256 $PortableArchive
if (-not $SkipInstaller) {
    Get-FileHash -Algorithm SHA256 (Join-Path $ProjectRoot "dist\installer\OpenPDF_Editor_$Version-x64.exe")
}
