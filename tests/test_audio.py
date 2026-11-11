import json
import queue
import struct
import threading
from urllib.parse import parse_qs, urlparse

import pytest
import websocket

from compass.audio import AudioCapture, LiveSession, deepgram_url, level
from compass.core import ApiConfig, CoachError


CONFIG = ApiConfig("g", "gemini-test", "d", "nova-3", "multi")
DEVICE = {"index": 1, "name": "Speakers", "rate": 48000, "channels": 2, "loopback": True}


def test_audio_format_and_auth_not_in_url():
    params = parse_qs(urlparse(deepgram_url(CONFIG, DEVICE)).query)
    assert params["encoding"] == ["linear16"]
    assert params["sample_rate"] == ["48000"]
    assert params["channels"] == ["2"]
    assert params["language"] == ["multi"]
    assert "key" not in params
    assert level(bytes(20)) == 0
    assert level(struct.pack("<4h", 10000, -10000, 10000, -10000)) > 0


class FakeSocket:
    def __init__(self, disconnect=False):
        self.events = queue.Queue()
        self.sent = []
        self.closed = False
        self.disconnect = disconnect

    def settimeout(self, _):
        pass

    def send(self, payload):
        self.sent.append(json.loads(payload)["type"])
        if self.sent[-1] == "Finalize":
            self.events.put(json.dumps({"type": "Results", "is_final": True, "from_finalize": True, "start": 0, "duration": 1,
                                       "channel": {"alternatives": [{"transcript": "Tell me about yourself?"}]}}))
        if self.sent[-1] == "CloseStream":
            self.events.put("")

    def send_binary(self, data):
        self.sent.append(data)

    def recv(self):
        if self.disconnect:
            return ""
        try:
            return self.events.get(timeout=0.05)
        except queue.Empty:
            raise websocket.WebSocketTimeoutException()

    def close(self, **_):
        self.closed = True


class FakeCapture:
    last = None

    def __init__(self, device):
        self.buffer = queue.Queue()
        self.buffer.put(bytes(64))
        self.failed = threading.Event()
        self.closed = False
        FakeCapture.last = self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


def test_stream_uses_binary_audio_flushes_and_cleans_up(monkeypatch):
    socket = FakeSocket()
    calls = []
    def connect(url, **kwargs):
        calls.append(kwargs)
        return socket
    monkeypatch.setattr("compass.audio.websocket.create_connection", connect)
    monkeypatch.setattr("compass.audio.AudioCapture", FakeCapture)
    events = []
    session = LiveSession(CONFIG, DEVICE, lambda k, v: events.append((k, v)), duration=0.01)
    assert session.run() == "Tell me about yourself?"
    assert any(isinstance(v, bytes) for v in socket.sent)
    assert socket.sent[-2:] == ["Finalize", "CloseStream"]
    assert ("final", "Tell me about yourself?") in events
    assert socket.closed and FakeCapture.last.closed
    assert calls[0]["header"] == ["Authorization: Token d"]


def test_disconnect_is_failure_not_false_success(monkeypatch):
    socket = FakeSocket(disconnect=True)
    monkeypatch.setattr("compass.audio.websocket.create_connection", lambda *_a, **_k: socket)
    monkeypatch.setattr("compass.audio.AudioCapture", FakeCapture)
    session = LiveSession(CONFIG, DEVICE, lambda *_: None, duration=0.01)
    with pytest.raises(CoachError, match="disconnected"):
        session.run()
    assert socket.closed


def test_http_handshake_error_omits_sensitive_headers(monkeypatch):
    def fail(*_a, **_k):
        raise websocket.WebSocketBadStatusException("secret response", status_code=401)
    monkeypatch.setattr("compass.audio.websocket.create_connection", fail)
    with pytest.raises(CoachError, match="HTTP 401") as caught:
        LiveSession(CONFIG, DEVICE, lambda *_: None).run()
    assert "secret response" not in str(caught.value)


def test_audio_callback_signals_loss_instead_of_silently_dropping():
    capture = AudioCapture.__new__(AudioCapture)
    capture.buffer = queue.Queue(maxsize=1)
    capture.failed = threading.Event()
    capture.pa = type("PA", (), {"paContinue": 0})
    capture.callback(bytes(8), 4, {}, 0)
    capture.callback(bytes(8), 4, {}, 0)
    assert capture.failed.is_set()


def test_microphone_rejected_before_network(monkeypatch):
    monkeypatch.setattr('compass.audio.websocket.create_connection', lambda *_a, **_k: pytest.fail('Must reject before connecting'))
    with pytest.raises(CoachError, match='system audio only'):
        LiveSession(CONFIG, dict(DEVICE, loopback=False), lambda *_: None).run()


def test_continuous_reconnect_preserves_stop(monkeypatch):
    from compass.audio import ContinuousSession, LiveSession
    calls = []
    statuses = []
    session = ContinuousSession(None, {}, lambda kind, value: statuses.append((kind, value)))
    class Stop:
        stopped = False
        def is_set(self): return self.stopped
        def set(self): self.stopped = True
        def wait(self, delay): return self.stopped
    session.stop_event = Stop()
    def run(inner):
        calls.append(inner.duration)
        if len(calls) == 1:
            raise OSError('Temporary disconnect')
        session.stop()
    monkeypatch.setattr(LiveSession, 'run', run)
    session.run()
    assert calls == [None, None]
    assert any('reconnecting' in value for kind, value in statuses)


def test_continuous_auth_error_stops_without_test(monkeypatch):
    import pytest
    from compass.audio import ContinuousSession, LiveSession
    from compass.core import CoachError
    def run(inner): raise CoachError('Deepgram connection rejected (HTTP 401).')
    monkeypatch.setattr(LiveSession, 'run', run)
    with pytest.raises(CoachError):
        ContinuousSession(None, {}, lambda *_: None).run()
