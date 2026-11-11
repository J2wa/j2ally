@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run Setup.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ALLY.spec
if errorlevel 1 goto fail
echo.
echo Built: dist\ALLY.exe
echo The single ALLY.exe file can be copied to another Windows x64 PC.
pause
exit /b 0
:fail
echo Build or tests failed. Read the error above.
pause
exit /b 1
