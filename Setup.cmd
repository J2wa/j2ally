@echo off
setlocal
cd /d "%~dp0"
echo ALLY - Windows setup
echo.
py -3.12 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.12 64-bit from https://www.python.org/downloads/windows/
    echo Include the Python launcher during installation, then run Setup.cmd again.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo.
echo Setup complete. Double-click Launch.cmd to open ALLY.
pause
exit /b 0
:fail
echo.
echo Setup failed. Read the error above, check your connection, and run Setup.cmd again.
pause
exit /b 1
