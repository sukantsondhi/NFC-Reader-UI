@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto setup_failed
)
".venv\Scripts\python.exe" -c "import PySide6.QtWebEngineWidgets, smartcard, qtawesome, ndef, markdown_it" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto setup_failed
)
".venv\Scripts\python.exe" app.py %*
if errorlevel 1 pause
exit /b
:setup_failed
echo Setup failed. Install 64-bit Python 3.11 or newer with the Python launcher.
echo See README.md for manual installation and troubleshooting.
pause
exit /b 1