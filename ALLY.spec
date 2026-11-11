# Run on Windows: python -m PyInstaller --noconfirm --clean ALLY.spec
from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / "assets"), "assets")],
    hiddenimports=["pyaudiowpatch", "pypdf", "docx", "PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="ALLY",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(project / "assets" / "ally.ico"))
