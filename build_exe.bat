@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\build_windows.ps1
if errorlevel 1 goto :error
echo Build and packaged self-test completed.
pause
exit /b 0
:error
echo Build failed. Review the error above.
pause
exit /b 1
