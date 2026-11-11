import json
import threading
from types import SimpleNamespace

import pytest

from test_ui import window, seed
from test_practice import QUESTIONS, RESUME, feedback
from conftest import pump
from compass.practice import parse_feedback


def start_mocked(window, app, monkeypatch):
    seed(window)
    window.resume.setPlainText(RESUME)
    page = window.practice
    page.count.setValue(3)
    monkeypatch.setattr('compass.practice_ui.generate_questions', lambda *args: QUESTIONS.copy())
    monkeypatch.setattr('compass.practice_ui.score_answer', lambda *args: parse_feedback(json.dumps(feedback(4)), RESUME))
    page.begin()
    pump(app, lambda: page.session.state == 'answering')
    return page


def test_practice_full_typed_flow_and_summary(window, app, monkeypatch):
    page = start_mocked(window, app, monkeypatch)
    window.go(3)
    assert window.stack.count() == 5
    assert not window.start_btn.isEnabled()  # microphone/live modes cannot overlap
    for i in range(3):
        assert f'Question {i + 1}/3' in page.question.text()
        page.answer.setPlainText('I use Python checks in QA.')
        page.submit_answer()
        assert not page.submit.isEnabled()
        pump(app, lambda: page.session.state == 'feedback')
        assert 'Score: 4/5' in page.feedback.toPlainText()
        assert 'Two strengths' in page.feedback.toPlainText()
        page.next_question()
    assert page.session.state == 'summary'
    assert 'Average score: 4.00/5' in page.feedback.toPlainText()
    assert 'Weakest question types:' in page.feedback.toPlainText()
    assert window.start_btn.isEnabled() is False  # consent still unchecked
    window.save_settings()
    saved = window.config_path.read_text()
    assert 'Python checks' not in saved and RESUME not in saved
    assert 'google-secret' not in saved and 'g-key' not in saved


def test_cancel_and_late_generation_ignored(window, app, monkeypatch):
    seed(window)
    page = window.practice
    page.count.setValue(3)
    release = threading.Event()
    def generate(*args):
        release.wait(2)
        return QUESTIONS.copy()
    monkeypatch.setattr('compass.practice_ui.generate_questions', generate)
    page.begin()
    epoch = page.epoch
    page.cancel_session()
    assert page.cancel.is_set()
    assert page.start.isEnabled()
    release.set()
    page.on_done(epoch, 'questions', QUESTIONS)
    assert page.session.state == 'cancelled' and not page.session.questions


def test_timeout_retains_answer_no_retry(window, app, monkeypatch):
    page = start_mocked(window, app, monkeypatch)
    release = threading.Event()
    calls = []
    def score(*args):
        calls.append(1)
        release.wait(2)
        return parse_feedback(json.dumps(feedback()), RESUME)
    monkeypatch.setattr('compass.practice_ui.score_answer', score)
    page.answer.setPlainText('Keep this draft')
    page.submit_answer()
    pump(app, lambda: len(calls) == 1)
    epoch = page.epoch
    page.timed_out()
    assert page.session.state == 'answering'
    assert page.answer.toPlainText() == 'Keep this draft'
    assert page.submit.isEnabled() and 'timed out' in page.status.text()
    release.set()
    page.on_done(epoch, 'feedback', parse_feedback(json.dumps(feedback()), RESUME))
    assert not page.session.results and len(calls) == 1


def test_microphone_recording_stop_review_and_cancel_cleanup(window, app, monkeypatch):
    page = start_mocked(window, app, monkeypatch)
    mic = {'name': 'Test mic', 'loopback': False, 'index': 2, 'rate': 48000, 'channels': 1, 'default': True}
    monkeypatch.setattr('compass.practice_ui.list_microphones', lambda: [mic])
    page.refresh_microphones()
    pump(app, lambda: page.devices.count() == 1)
    sessions = []
    class Session:
        def __init__(self, config, device, emit, **kwargs):
            assert kwargs == {'duration': 120, 'source': 'practice_microphone'}
            self.emit = emit; self.stopped = threading.Event(); sessions.append(self)
        def run(self):
            self.emit('interim', 'I use')
            self.emit('final', 'I use Python.')
            self.stopped.wait(2)
        def stop(self): self.stopped.set()
    monkeypatch.setattr('compass.practice_ui.LiveSession', Session)
    page.record_answer()
    pump(app, lambda: 'Python' in page.answer.toPlainText())
    assert not page.submit.isEnabled()
    page.stop_recording()
    pump(app, lambda: page.microphone is None)
    assert page.submit.isEnabled() and page.answer.toPlainText() == 'I use Python.'
    page.record_answer()
    epoch = page.audio_epoch
    page.cancel_session()
    assert sessions[-1].stopped.is_set()
    # Cancel retains the audio slot until the worker exits; late text is discarded.
    page.on_audio(epoch, 'final', 'Obsolete words')
    pump(app, lambda: page.microphone is None)
    assert 'Obsolete' not in page.answer.toPlainText()


def test_speech_unavailable_graceful(window, app, monkeypatch):
    page = start_mocked(window, app, monkeypatch)
    monkeypatch.setattr('compass.practice_ui.os', SimpleNamespace(name='posix'))
    page.read_question()
    assert 'unavailable' in page.status.text()
    assert page.question.text() and page.submit.isEnabled()
