"""Qt Practice page. Worker results are epoch-scoped; session data stays in memory."""
import html
import os
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Signal, QTimer, QProcess, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QSpinBox, QPushButton, QPlainTextEdit, QTextBrowser)

from .audio import LiveSession, list_microphones
from .core import CoachError, safe_error
from .practice import (PracticeSession, FOCUSES, DIFFICULTIES, REQUEST_SECONDS,
                       generate_questions, score_answer)
from .transport import Cancellation


class PracticeBus(QObject):
    done = Signal(int, str, object)
    failed = Signal(int, str, str)
    audio = Signal(int, str, object)


class PracticePage(QWidget):
    changed = Signal()

    def __init__(self, config, context, transport, available, parent=None):
        super().__init__(parent)
        self.get_config, self.get_context = config, context
        self.transport, self.available = transport, available
        self.session = PracticeSession()
        self.epoch = 0
        self.audio_epoch = 0
        self.record_epoch = None
        self.request_kind = None
        self.cancel = Cancellation()
        self.microphone = None
        self.audio_stopping = False
        self.closed = False
        self.bus = PracticeBus(self)
        self.bus.done.connect(self.on_done)
        self.bus.failed.connect(self.on_failed)
        self.bus.audio.connect(self.on_audio)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)
        self.speech = QProcess(self)
        self.speech.finished.connect(self.speech_finished)
        self.speech.errorOccurred.connect(lambda *_: self.speech_failed())
        self.speech_timer = QTimer(self)
        self.speech_timer.setSingleShot(True)
        self.speech_timer.timeout.connect(self.speech_timeout)
        layout = QVBoxLayout(self)
        heading = QLabel("Practice interview")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        note = QLabel("ALLY asks; you answer. Uses your imported resume and job description. Feedback is AI-generated coaching, not a hiring assessment.")
        note.setWordWrap(True)
        layout.addWidget(note)
        options = QHBoxLayout()
        self.focus = QComboBox(); self.focus.addItems(FOCUSES); self.focus.setCurrentText("Mixed")
        self.difficulty = QComboBox(); self.difficulty.addItems(DIFFICULTIES); self.difficulty.setCurrentText("Intermediate")
        self.count = QSpinBox(); self.count.setRange(3, 15); self.count.setValue(5)
        for name, widget in (("Focus", self.focus), ("Difficulty", self.difficulty), ("Questions", self.count)):
            options.addWidget(QLabel(name)); options.addWidget(widget)
        layout.addLayout(options)
        row = QHBoxLayout()
        self.start = self.button("Start practice", self.begin, row)
        self.cancel_button = self.button("Cancel session", self.cancel_session, row)
        layout.addLayout(row)
        self.status = QLabel("Add API keys and import your context in the first two pages. Nothing from Practice is saved automatically.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.question = QLabel("Your first question will appear here.")
        self.question.setWordWrap(True)
        self.question.setTextFormat(Qt.TextFormat.PlainText)
        self.question.setStyleSheet("font-size: 22px; padding: 14px; background: #18283f; border-radius: 8px;")
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.read_button = self.button("Read question aloud", self.read_question, row)
        self.silence_button = self.button("Stop voice", self.stop_speech, row)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.setMinimumWidth(0)
        row.addWidget(self.devices, 1)
        self.refresh = self.button("Find microphones", self.refresh_microphones, row)
        self.record = self.button("Record answer", self.record_answer, row)
        self.stop_record = self.button("Stop recording", self.stop_recording, row)
        layout.addLayout(row)
        self.interim = QLabel("")
        self.interim.setWordWrap(True)
        self.interim.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.interim)
        self.answer = QPlainTextEdit()
        self.answer.setPlaceholderText("Type your answer, or record with your microphone. Review the transcript before submitting.")
        self.answer.setMinimumHeight(130)
        layout.addWidget(self.answer, 1)
        row = QHBoxLayout()
        self.submit = self.button("Submit answer", self.submit_answer, row)
        self.next_button = self.button("Next question", self.next_question, row)
        layout.addLayout(row)
        self.feedback = QTextBrowser()
        self.feedback.setOpenExternalLinks(False)
        self.feedback.setOpenLinks(False)
        self.feedback.setMinimumHeight(180)
        layout.addWidget(self.feedback, 1)
        self.update_controls()

    @staticmethod
    def button(text, fn, layout):
        result = QPushButton(text); result.clicked.connect(fn); layout.addWidget(result)
        return result

    @property
    def active(self):
        return self.session.state in ("generating", "answering", "grading", "feedback")

    def update_controls(self):
        answering = self.session.state == "answering"
        recording = self.microphone is not None
        waiting = self.request_kind is not None
        self.start.setEnabled(not self.active and not waiting and not recording)
        self.cancel_button.setEnabled(self.active or waiting or recording)
        for widget in (self.focus, self.difficulty, self.count):
            widget.setEnabled(not self.active and not waiting)
        self.answer.setReadOnly(not answering or waiting)
        self.submit.setEnabled(answering and not recording and not waiting)
        self.next_button.setEnabled(self.session.state == "feedback" and not recording)
        self.read_button.setEnabled(answering and not recording and not waiting)
        self.record.setEnabled(answering and not recording and not waiting and self.devices.count() > 0 and self.speech.state() == QProcess.ProcessState.NotRunning)
        self.stop_record.setEnabled(recording and not self.audio_stopping)
        self.devices.setEnabled(not recording)
        self.refresh.setEnabled(not recording and not waiting)
        self.silence_button.setEnabled(self.speech.state() != QProcess.ProcessState.NotRunning)
        self.changed.emit()

    def begin(self):
        if self.active or self.request_kind or self.microphone:
            return
        if not self.available():
            self.status.setText("Stop Live coach and any active audio/API test or answer before starting Practice.")
            return
        try:
            resume, job = self.get_context()
            config = self.get_config()
            if not config.google_key:
                raise CoachError("Add your Google API key in API & audio.")
            self.session.begin(resume, job, self.focus.currentText(), self.difficulty.currentText(), self.count.value())
        except Exception as exc:
            self.status.setText(str(exc)); return
        self.feedback.clear(); self.answer.clear(); self.question.setText("Preparing your questions…")
        focus, difficulty, count = self.session.focus, self.session.difficulty, self.session.count
        self.launch("questions", lambda cancel: generate_questions(config, resume, job, focus,
                    difficulty, count, cancel, self.transport))

    def launch(self, kind, work):
        self.epoch += 1
        epoch = self.epoch
        self.cancel = Cancellation()
        cancel = self.cancel
        self.request_kind = kind
        config = self.get_config()
        self.status.setText("Generating questions…" if kind == "questions" else "Evaluating your answer…")
        self.deadline.start(REQUEST_SECONDS * 1000)
        self.update_controls()
        def run():
            try:
                value = work(cancel)
                if not self.closed:
                    self.bus.done.emit(epoch, kind, value)
            except Exception as exc:
                if not self.closed:
                    self.bus.failed.emit(epoch, kind, safe_error(exc, config.google_key, config.deepgram_key))
        threading.Thread(target=run, daemon=True, name=f"practice:{kind}:{epoch}").start()

    def on_done(self, epoch, kind, value):
        if self.closed or epoch != self.epoch or kind != self.request_kind:
            return
        self.deadline.stop(); self.request_kind = None
        try:
            if kind == "questions":
                self.session.accept_questions(value)
                self.show_question()
            else:
                self.session.accept_feedback(self.submitted_answer, value)
                self.show_feedback(value)
                self.status.setText("Review your feedback, then continue.")
        except Exception as exc:
            self.recover(kind, str(exc))
        self.update_controls()

    def on_failed(self, epoch, kind, message):
        if self.closed or epoch != self.epoch or kind != self.request_kind:
            return
        self.deadline.stop(); self.request_kind = None
        self.recover(kind, message)
        self.update_controls()

    def recover(self, kind, message):
        self.session.state = "idle" if kind == "questions" else "answering"
        self.status.setText(message + " No automatic retry. You may try again manually.")

    def timed_out(self):
        if not self.request_kind:
            return
        kind = self.request_kind
        self.cancel.set(); self.epoch += 1; self.request_kind = None
        self.recover(kind, "Practice request timed out after 45 seconds.")
        self.update_controls()

    def submit_answer(self):
        if self.microphone or self.request_kind or self.session.state != "answering":
            return
        try:
            answer = self.answer.toPlainText().strip()
            self.session.submit(answer)
        except Exception as exc:
            self.status.setText(str(exc)); return
        self.stop_speech()
        self.submitted_answer = answer
        session, config, question = self.session, self.get_config(), self.session.current.copy()
        self.launch("feedback", lambda cancel: score_answer(config, session.resume, session.job, question,
                    answer, session.difficulty, cancel, self.transport))

    def show_question(self):
        question = self.session.current
        self.question.setText(f"Question {self.session.index + 1}/{self.session.count} · {question['type'].title()}\n{question['question']}")
        self.answer.clear(); self.feedback.clear(); self.interim.clear()
        self.status.setText("Type an answer or select a microphone. Recording is sent to Deepgram; submit only after reviewing the transcript.")

    def show_feedback(self, value):
        # Render model strings as escaped text, never raw HTML/links.
        esc = html.escape
        items = lambda values: '<ul>' + ''.join('<li>' + esc(v) + '</li>' for v in values) + '</ul>'
        self.feedback.setHtml(f"<h2>Score: {value['score']}/5</h2><h3>Two strengths</h3>" + items(value['strengths']) +
            '<h3>Two improvements</h3>' + items(value['improvements']) + '<h3>Stronger sample answer</h3><p>' +
            esc(value['sample_answer']) + '</p><h3>Missing facts / confirm</h3>' + items(value['missing_facts'] or ['No missing facts flagged by the model. Review the sample against your resume.']))

    def next_question(self):
        try:
            self.session.next()
        except CoachError as exc:
            self.status.setText(str(exc)); return
        self.stop_speech()
        if self.session.state == "summary":
            summary = self.session.summary()
            self.question.setText("Practice complete")
            self.status.setText(f"Completed {len(self.session.results)} questions. Scores are coaching estimates.")
            rows = ''.join(f"<li>{html.escape(t['type'].title())}: {t['average']:.2f}/5 ({t['count']} questions)</li>" for t in summary['types'])
            weakest = ', '.join(summary['weakest_types'])
            self.feedback.setHtml(f"<h2>Average score: {summary['average']:.2f}/5</h2><h3>Scores by question type</h3><ul>{rows}</ul><p>Weakest question types: {html.escape(weakest)}</p>")
        else:
            self.show_question()
        self.update_controls()

    def refresh_microphones(self):
        if self.microphone:
            return
        self.audio_epoch += 1
        epoch = self.audio_epoch
        self.devices.clear(); self.refresh.setEnabled(False)
        def work():
            try:
                devices = list_microphones()
                if not self.closed:
                    self.bus.audio.emit(epoch, "devices", devices)
            except Exception:
                if not self.closed:
                    self.bus.audio.emit(epoch, "device_error", "Microphones unavailable. You can still type your answers.")
        threading.Thread(target=work, daemon=True).start()

    def record_answer(self):
        if self.session.state != "answering" or self.microphone or self.request_kind:
            return
        if self.speech.state() != QProcess.ProcessState.NotRunning:
            self.status.setText("Stop the spoken question before recording."); return
        config, device = self.get_config(), self.devices.currentData()
        if not config.deepgram_key or not device:
            self.status.setText("Add a Deepgram key and select a microphone, or type your answer."); return
        self.audio_epoch += 1
        epoch = self.audio_epoch
        self.record_epoch = epoch
        self.audio_stopping = False
        self.microphone = LiveSession(config, device, lambda kind, value: self.bus.audio.emit(epoch, kind, value),
                                      duration=120, source="practice_microphone")
        microphone = self.microphone
        self.status.setText("Recording microphone · maximum 2 minutes · press Stop recording, then review and submit.")
        self.update_controls()
        def work():
            try:
                microphone.run()
                if not self.closed:
                    self.bus.audio.emit(epoch, "recording_done", None)
            except Exception as exc:
                if not self.closed:
                    self.bus.audio.emit(epoch, "recording_error", safe_error(exc, config.google_key, config.deepgram_key))
        threading.Thread(target=work, daemon=True).start()

    def stop_recording(self):
        if self.microphone:
            self.audio_stopping = True
            self.microphone.stop()
            self.status.setText("Finishing transcription…")
            self.update_controls()

    def on_audio(self, epoch, kind, value):
        if self.closed:
            return
        if epoch != self.audio_epoch:
            if epoch == self.record_epoch and kind in ("recording_done", "recording_error"):
                self.microphone = None
                self.audio_stopping = False
                self.update_controls()
            return
        if kind == "devices":
            self.devices.clear()
            for device in value:
                if not device.get("loopback"):
                    self.devices.addItem(device['name'], device)
            self.status.setText("Choose your microphone." if self.devices.count() else "No microphone found. You can type your answer.")
        elif kind in ("recording_done", "recording_error"):
            self.microphone = None; self.audio_stopping = False; self.interim.clear()
            self.status.setText("Review the transcript and submit when ready." if kind == "recording_done" else str(value) + " Recording stopped; no retry. You can edit the transcript or type.")
        elif kind == "device_error":
            self.status.setText(str(value))
        elif kind == "interim":
            self.interim.setText(str(value))
        elif kind == "final":
            cursor = self.answer.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText((" " if self.answer.toPlainText() else "") + str(value))
            self.answer.setTextCursor(cursor)
        self.update_controls()

    def read_question(self):
        if self.session.state != "answering" or self.microphone:
            return
        if os.name != "nt":
            self.status.setText("Windows speech is unavailable here. Read the question text instead."); return
        if self.speech.state() != QProcess.ProcessState.NotRunning:
            return
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        script = "$ErrorActionPreference = 'Stop'; [Console]::InputEncoding = [System.Text.Encoding]::UTF8; $text = [Console]::In.ReadToEnd(); $voice = New-Object -ComObject SAPI.SpVoice; [void]$voice.Speak($text, 16)"
        self.speech.start(str(executable), ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script])
        # User/model text is stdin data, never interpolated into PowerShell code.
        self.speech.write(self.session.current['question'].encode('utf-8'))
        self.speech.closeWriteChannel()
        self.speech_timer.start(30000)
        self.status.setText("Reading question with Windows speech…")
        self.update_controls()

    def stop_speech(self):
        self.speech_timer.stop()
        if self.speech.state() != QProcess.ProcessState.NotRunning:
            self.speech.kill()

    def speech_finished(self, code, *_):
        self.speech_timer.stop()
        if not self.closed:
            if code:
                self.status.setText("Windows speech stopped or unavailable. The text question is still available.")
            self.update_controls()

    def speech_failed(self):
        if not self.closed:
            self.status.setText("Windows speech unavailable. The text question is still available.")
            self.update_controls()

    def speech_timeout(self):
        self.stop_speech()
        self.status.setText("Spoken question stopped after 30 seconds. Read the question text instead.")

    def cancel_session(self):
        self.deadline.stop(); self.cancel.set(); self.epoch += 1; self.request_kind = None
        self.audio_epoch += 1
        if self.microphone:
            self.microphone.stop()
        self.audio_stopping = self.microphone is not None
        self.stop_speech()
        self.session.cancel()
        self.interim.clear()
        self.status.setText("Practice cancelled. Late responses will be discarded. Start a new session when ready.")
        self.update_controls()

    def shutdown(self):
        self.closed = True
        self.cancel_session()
