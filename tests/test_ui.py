import json

import pytest

from compass.core import CoachError
from compass.ui import MainWindow, STYLE
from conftest import pump


DEVICE = {"index": 1, "name": "Test headphones", "rate": 48000, "channels": 2, "loopback": True, "default": True}


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("compass.ui.list_devices", lambda: [DEVICE.copy()])
    monkeypatch.setattr("compass.ui.set_capture_protection", lambda *_: (True, "Capture exclusion requested · verify in your meeting app"))
    app.setStyleSheet(STYLE)
    w = MainWindow(app)
    w.show()
    pump(app, lambda: not w.busy)
    yield w
    w.closed = True
    w.close()
    app.processEvents()


def seed(window):
    window.google_key.setText("g-key")
    window.google_model.setCurrentText("gemini-test")
    window.deepgram_key.setText("d-key")
    window.resume.setPlainText("Candidate has Python experience.")
    window.job.setPlainText("Role requires Python.")


def test_context_consent_and_single_audio_check(window, app, monkeypatch):
    seed(window)
    assert not window.start_btn.isEnabled()
    def answer(_config, _prompt, on_text, *_):
        on_text("Ready")
        return "Ready"
    monkeypatch.setattr("compass.ui.stream_google", answer)
    window.test_google()
    pump(app, lambda: "google_test" not in window.busy)
    assert window.preflight.google
    assert window.ask_btn.isEnabled()
    assert not window.start_btn.isEnabled()
    monkeypatch.setattr("compass.ui.LiveSession.run", lambda _: "Test interview question")
    window.test_audio()
    pump(app, lambda: "audio_test" not in window.busy)
    assert window.preflight.audio
    assert not window.start_btn.isEnabled()
    window.consent.setChecked(True)
    assert window.start_btn.isEnabled()
    window.audio_language.setCurrentText("multi")
    assert window.start_btn.isEnabled()
    assert window.start_btn.text() == "Test + start coach"
    assert window.preflight.audio is None


def test_no_speech_does_not_pass_preflight(window, app, monkeypatch):
    seed(window)
    monkeypatch.setattr("compass.ui.LiveSession.run", lambda _: "")
    window.test_audio()
    pump(app, lambda: "audio_test" not in window.busy)
    assert window.preflight.audio is None
    assert "No speech recognized" in window.audio_status.text()
    assert not window.start_btn.isEnabled()


def test_google_stale_success_ignored(window):
    seed(window)
    sig = window.config().google_signature()
    window.google_key.setText("new-key")
    window.on_done("google_test", (sig, "Ready"))
    assert window.preflight.google is None


def test_manual_question_context_and_streaming(window, app, monkeypatch):
    seed(window)
    window.preflight.google = window.config().google_signature()
    window.update_ready()
    seen = []
    def generate(config, prompt, on_text, cancel, screenshot=None):
        seen.append(json.loads(prompt))
        on_text("## Suggested answer\nI use Python.")
        return "## Suggested answer\nI use Python."
    monkeypatch.setattr("compass.ui.stream_google", generate)
    window.question.setPlainText("Tell me about your skills")
    window.ask()
    pump(app, lambda: "answer" not in window.busy)
    assert "I use Python" in window.answer_view.toPlainText()
    assert seen[0]["candidate_resume_and_notes"] == "Candidate has Python experience."
    assert window.answers[0][0] == "Tell me about your skills"
    assert not window.session


def test_settings_never_save_plaintext_keys_or_resume(window):
    seed(window)
    window.save_settings()
    data = window.config_path.read_text()
    assert "g-key" not in data and "d-key" not in data
    assert "Candidate has Python" not in data
    assert "encrypted_keys" not in data
    assert "google_model" in data


def test_capture_applies_after_topmost_toggle(window, app, monkeypatch):
    calls = []
    monkeypatch.setattr("compass.ui.set_capture_protection", lambda hwnd, enabled: (calls.append((hwnd, enabled)) or (True, "OK")))
    window.protection.setChecked(False)
    app.processEvents()
    assert calls and calls[-1][1] is False
    window.protection.setChecked(True)
    window.on_top.setChecked(True)
    app.processEvents()
    assert calls[-1][1] is True


def test_capture_protects_app_dialogs(window, app, monkeypatch):
    from PySide6.QtWidgets import QDialog
    calls = []
    monkeypatch.setattr("compass.ui.set_capture_protection", lambda hwnd, enabled: (calls.append((hwnd, enabled)) or (True, "OK")))
    dialog = QDialog(window)
    dialog.show()
    app.processEvents()
    assert (int(dialog.winId()), True) in calls
    dialog.close()


def test_cancellation_prevents_stale_answer_overwrite(window):
    seed(window)
    window.answer_epoch = 1
    window.cancel_answer()
    window.on_event("answer_chunk", (1, "obsolete"))
    window.on_done("answer", (1, "old question", "obsolete"))
    assert "obsolete" not in window.answer_view.toPlainText()
    assert not window.answers


def test_auto_turns_merge_and_wait_while_busy(window):
    seed(window)
    window.session = object()
    window.auto.setChecked(True)
    window.on_event("utterance", "Tell me")
    window.on_event("speaking", "")
    assert not window.timer.isActive()
    window.on_event("utterance", "about yourself?")
    assert window.pending_auto == "Tell me about yourself?"
    window.busy.add("answer")
    window.auto_answer()
    assert window.pending_auto == "Tell me about yourself?"
    window.busy.clear()
    window.session = None


def test_start_stop_session_releases_controls(window, app, monkeypatch):
    import threading
    from compass.audio import LiveSession
    seed(window)
    config = window.config()
    window.preflight.google = config.google_signature()
    window.preflight.audio = config.audio_signature(DEVICE)
    window.consent.setChecked(True)
    def run(session):
        session.emit("status", "Listening")
        session.stop_event.wait(2)
        return ""
    monkeypatch.setattr(LiveSession, "run", run)
    window.update_ready()
    assert window.start_btn.isEnabled()
    window.start_session()
    assert window.session
    assert not window.devices.isEnabled()
    window.stop_session()
    pump(app, lambda: window.session is None)
    assert window.devices.isEnabled()
    assert window.start_btn.isEnabled()


def test_stop_does_not_start_another_auto_answer_from_flushed_audio(window):
    seed(window)
    window.auto.setChecked(True)
    window.stopping = True
    window.session = object()
    window.on_event("utterance", "A final trailing sentence")
    assert not window.timer.isActive()
    assert not window.pending_auto
    window.session = None


def test_one_audio_test_then_reuse_for_start_stop(window, app, monkeypatch):
    seed(window)
    window.consent.setChecked(True)
    calls = []
    def run(session):
        calls.append(session.duration)
        if session.duration is not None:
            return 'An interview question'
        session.stop_event.wait(2)
        return ''
    monkeypatch.setattr('compass.ui.LiveSession.run', run)
    assert window.preflight.google is None  # no mandatory separate Google test
    window.start_session()
    pump(app, lambda: window.session is not None)
    assert calls == [4, None]
    window.stop_session()
    pump(app, lambda: window.session is None)
    window.start_session()
    pump(app, lambda: calls == [4, None, None])
    window.stop_session()
    pump(app, lambda: window.session is None)


def test_opacity_font_persist_and_focus_expands_answer(window, app):
    window.opacity.setValue(65)
    assert abs(window.windowOpacity() - 0.65) < .01
    window.answer_font.setValue(28)
    window.save_settings()
    stored = json.loads(window.config_path.read_text())
    assert stored['opacity'] == 65 and stored['answer_font'] == 28
    window.go(2)
    app.processEvents()
    width = window.answer_view.width()
    window.toggle_answer_focus()
    app.processEvents()
    assert not window.transcript_panel.isVisible()
    assert window.answer_view.width() > width


def test_screenshot_capture_restores_window_and_sends_png(window, app, monkeypatch):
    from PySide6.QtGui import QPixmap, QColor
    seed(window)
    sent = []
    monkeypatch.setattr(window, 'generate', lambda question, screenshot=None: sent.append((question, screenshot)))
    class Screen:
        def grabWindow(self, handle):
            assert handle == 0
            image = QPixmap(300, 200)
            image.fill(QColor('white'))
            return image
    window.capturing = True
    window.hide()
    window.finish_capture(Screen())
    assert window.isVisible() and not window.capturing
    assert sent[0][1].startswith(b'\x89PNG')
    assert 'job description and my resume' in sent[0][0]


def test_failed_screenshot_restores_window(window, monkeypatch):
    from PySide6.QtGui import QPixmap
    class Screen:
        def grabWindow(self, _): return QPixmap()
    monkeypatch.setattr(window, 'generate', lambda *_a, **_k: pytest.fail('Should not send blank capture'))
    window.hide()
    window.capturing = True
    window.finish_capture(Screen())
    assert window.isVisible() and not window.capturing
    assert 'could not be captured' in window.footer.text()


def test_microphone_devices_never_shown(window):
    window.on_done('devices', [dict(DEVICE, loopback=False), DEVICE])
    assert window.devices.count() == 1
    assert window.devices.currentData()['loopback']


def test_started_coach_does_not_retest_after_error(window, monkeypatch):
    seed(window)
    window.consent.setChecked(True)
    window.coach_started = True
    window.on_failed('session', 'Connection failed')
    monkeypatch.setattr(window, 'test_audio', lambda **kw: pytest.fail('Repeated test'))
    monkeypatch.setattr(window, 'launch', lambda *args: None)
    window.start_session()
    assert window.session is not None
    assert window.start_btn.text() == 'Start coach'
    window.session = None


def test_layout_modes_and_small_window(window, app):
    from PySide6.QtCore import Qt
    window.go(2)
    window.resize(720, 650)
    app.processEvents()
    assert window.width() == 720
    assert window.sidebar.isHidden()
    assert window.coach_splitter.orientation() == Qt.Orientation.Vertical
    window.layout_mode.setCurrentIndex(1)
    assert window.coach_splitter.orientation() == Qt.Orientation.Horizontal
    window.layout_mode.setCurrentIndex(2)
    assert window.coach_splitter.orientation() == Qt.Orientation.Vertical
    assert window.transcript_panel.maximumWidth() > 310
