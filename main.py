import sys

from compass.ui import main

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        import json
        import os
        from pathlib import Path
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        import pyaudiowpatch
        import requests
        import websocket
        import pypdf
        import docx
        import compass.ui as ui
        ui.list_devices = lambda: []
        app = QApplication([])
        app.setStyleSheet(ui.STYLE)
        window = ui.MainWindow(app)
        window.show()
        app.processEvents()
        Path(sys.argv[2]).write_text(json.dumps({"title": window.windowTitle(), "frozen": bool(getattr(sys, "frozen", False)), "imports": "ok", "ui": "ok"}), encoding="utf-8")
        window.closed = True
        window.close()
    else:
        main()
