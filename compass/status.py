"""Non-modal status and actionable error feedback."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QProgressBar


class StatusStrip(QWidget):
    fixRequested = Signal(str)

    def __init__(self, listening, meter, parent=None):
        super().__init__(parent)
        self.setObjectName('statusStrip')
        self.target = 'API & audio'
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(4)
        row = QHBoxLayout()
        self.listening = listening
        self.meter = meter; self.meter.setFixedWidth(70); self.meter.setAccessibleName('System audio level')
        self.deepgram = QLabel('Deepgram: unverified')
        self.gemini = QLabel('Gemini: unverified')
        self.answer = QLabel('Answer: idle')
        for widget in (listening, meter, self.deepgram, self.gemini, self.answer):
            row.addWidget(widget)
        row.addStretch(); layout.addLayout(row)
        self.banner = QWidget(); self.banner.setObjectName('errorBanner')
        error_row = QHBoxLayout(self.banner); error_row.setContentsMargins(8, 4, 8, 4)
        self.error = QLabel(''); self.error.setWordWrap(True); self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.fix = QPushButton('Fix →'); self.fix.setAccessibleName('Fix the last error in settings')
        self.dismiss = QPushButton('Dismiss')
        error_row.addWidget(self.error, 1); error_row.addWidget(self.fix); error_row.addWidget(self.dismiss)
        layout.addWidget(self.banner); self.banner.hide()
        self.fix.clicked.connect(lambda: self.fixRequested.emit(self.target))
        self.dismiss.clicked.connect(self.banner.hide)

    def show_error(self, message, target='API & audio'):
        self.target = target
        self.error.setText(message)
        self.banner.show()

    def set_answer(self, state):
        self.answer.setText('Answer: ' + state)

    def compact(self, enabled):
        self.deepgram.setVisible(not enabled); self.gemini.setVisible(not enabled)
        self.answer.setVisible(not enabled); self.meter.setVisible(not enabled)
