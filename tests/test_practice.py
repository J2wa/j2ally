import json
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from compass.core import ApiConfig, CoachError
from compass.practice import (PracticeSession, parse_questions, parse_feedback, request_json,
                              generate_questions, score_answer)
from compass.transport import Cancellation
from compass.audio import LiveSession, list_microphones
from test_audio import FakeCapture, FakeSocket, DEVICE

RESUME = 'I have Python experience. I led QA reviews.'
CONFIG = ApiConfig('google-secret', 'gemini-2.5-flash', 'deepgram-secret')
QUESTIONS = [{'type': 'technical', 'question': 'How do you test Python?'},
             {'type': 'behavioral', 'question': 'Describe a QA challenge.'},
             {'type': 'technical', 'question': 'How do you review code?'}]


def feedback(score=3):
    return {'score': score, 'strengths': ['Clear approach', 'Relevant example'],
            'improvements': ['Add checks', 'Clarify outcome'],
            'sample_answer': [{'text': 'I have Python experience.', 'resume_quotes': ['I have Python experience.'], 'needs_confirmation': False}],
            'missing_facts': []}


def test_question_generation_parsing():
    text = json.dumps({'questions': QUESTIONS})
    assert parse_questions('```json\n' + text + '\n```', 3, 'Mixed') == QUESTIONS
    for value in ('not json', '[]', '{}', json.dumps({'questions': QUESTIONS[:2]}),
                  json.dumps({'questions': [QUESTIONS[0]] * 3})):
        with pytest.raises(CoachError):
            parse_questions(value, 3, 'Mixed')
    with pytest.raises(CoachError):
        parse_questions(text, 3, 'Technical')


@pytest.mark.parametrize('score', [0, 6, True, 3.5, '3', None])
def test_invalid_scores(score):
    with pytest.raises(CoachError, match='integer'):
        parse_feedback(json.dumps(feedback(score)), RESUME)


def test_scoring_parsing_and_grounding():
    parsed = parse_feedback(json.dumps(feedback(4)), RESUME)
    assert parsed['score'] == 4 and parsed['sample_answer'] == 'I have Python experience.'
    value = feedback()
    value['sample_answer'][0]['resume_quotes'] = []
    parsed = parse_feedback(json.dumps(value), RESUME)
    assert parsed['sample_answer'].startswith('[Confirm with your own example]')
    assert parsed['missing_facts']
    value['sample_answer'][0]['resume_quotes'] = ['I worked at Imaginary Inc.']
    with pytest.raises(CoachError, match='absent'):
        parse_feedback(json.dumps(value), RESUME)


@pytest.mark.parametrize('value', ['```json\nbroken\n```', '{}', 'null', '[]', '{"score":NaN}', '{"score":4,"strengths":["one"]}'])
def test_malformed_feedback(value):
    with pytest.raises(CoachError):
        parse_feedback(value, RESUME)


class Response:
    status_code = 200
    def __init__(self, text):
        self.body = json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]}).encode()
        self.closed = False
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.closed = True
    def iter_content(self, **kwargs): yield self.body


class Transport:
    def __init__(self, *texts): self.texts = list(texts); self.calls = []; self.response = None
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        self.response = Response(self.texts.pop(0))
        return self.response


def test_gemini_question_and_scoring_requests_mocked():
    transport = Transport(json.dumps({'questions': QUESTIONS}), json.dumps(feedback()))
    questions = generate_questions(CONFIG, RESUME, 'QA role', 'Mixed', 'Intermediate', 3, Cancellation(), transport)
    result = score_answer(CONFIG, RESUME, 'QA role', questions[0], 'I test carefully', 'Intermediate', Cancellation(), transport)
    assert result['score'] == 3 and len(transport.calls) == 2
    url, kwargs = transport.calls[0]
    assert CONFIG.google_key not in url
    assert kwargs['timeout'] == (5, 15)
    assert kwargs['json']['generationConfig']['responseMimeType'] == 'application/json'
    assert 'Never invent' in kwargs['json']['systemInstruction']['parts'][0]['text']
    assert transport.response.closed


def test_bad_model_output_is_not_retried():
    transport = Transport('not json')
    with pytest.raises(CoachError):
        generate_questions(CONFIG, RESUME, 'QA role', 'Mixed', 'Intermediate', 3, Cancellation(), transport)
    assert len(transport.calls) == 1


def test_request_cancelled_before_send_and_deadline():
    cancel = Cancellation(); cancel.set()
    transport = Transport('{}')
    with pytest.raises(CoachError, match='cancelled'):
        request_json(CONFIG, 'task', {}, cancel, transport)
    assert not transport.calls
    times = iter([0, 46])
    with pytest.raises(CoachError, match='timed out'):
        request_json(CONFIG, 'task', {}, Cancellation(), transport, clock=lambda: next(times))
    assert len(transport.calls) == 1


def test_session_state_and_weakest_types():
    session = PracticeSession()
    with pytest.raises(CoachError): session.submit('answer')
    with pytest.raises(CoachError): session.begin(RESUME, 'job', 'Mixed', 'Intermediate', 16)
    session.begin(RESUME, 'job', 'Mixed', 'Intermediate', 3)
    assert session.state == 'generating'
    session.accept_questions(QUESTIONS)
    for score in (4, 2, 3):
        assert session.state == 'answering'
        session.submit('my answer')
        assert session.state == 'grading'
        session.accept_feedback('my answer', parse_feedback(json.dumps(feedback(score)), RESUME))
        assert session.state == 'feedback'
        with pytest.raises(CoachError): session.submit('duplicate')
        session.next()
    assert session.state == 'summary'
    assert session.summary()['average'] == 3
    assert session.summary()['weakest_types'] == ['behavioral']
    session.cancel()
    with pytest.raises(CoachError): session.accept_questions(QUESTIONS)
    assert session.state == 'cancelled'


def test_practice_uses_deepgram_microphone_live_rejects_it(monkeypatch):
    socket = FakeSocket()
    monkeypatch.setattr('compass.audio.websocket.create_connection', lambda *_a, **_k: socket)
    monkeypatch.setattr('compass.audio.AudioCapture', FakeCapture)
    mic = dict(DEVICE, loopback=False, name='Microphone')
    events = []
    session = LiveSession(CONFIG, mic, lambda k, v: events.append((k, v)), duration=.01, source='practice_microphone')
    assert session.run() == 'Tell me about yourself?'
    assert ('final', 'Tell me about yourself?') in events
    assert socket.closed and FakeCapture.last.closed
    with pytest.raises(CoachError, match='system audio only'):
        LiveSession(CONFIG, mic, lambda *_: None).run()
    with pytest.raises(CoachError, match='microphone'):
        LiveSession(CONFIG, DEVICE, lambda *_: None, source='practice_microphone').run()
