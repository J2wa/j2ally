@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run Setup.cmd first.
    pause
    exit /b 1
)
start "ALLY" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
