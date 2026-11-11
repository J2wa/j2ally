from __future__ import annotations

import json
import math
import queue
import struct
import sys
import threading
import time
from urllib.parse import urlencode

import websocket

from .turns import SPEEDS
from .core import ApiConfig, CoachError, Utterances


def audio_module():
    if sys.platform != "win32":
        raise CoachError("Live Windows audio is available on Windows. Manual questions work here.")
    try:
        import pyaudiowpatch as pa
        return pa
    except ImportError as exc:
        raise CoachError("Windows audio component missing. Run Setup.cmd again.") from exc


def list_devices(source="system") -> list[dict]:
    pa = audio_module()
    result = []
    with pa.PyAudio() as p:
        try:
            default_loop = int(p.get_default_wasapi_loopback()["index"])
        except (OSError, ValueError, KeyError):
            default_loop = -1
        try:
            default_mic = int(p.get_default_input_device_info()["index"])
        except (OSError, ValueError, KeyError):
            default_mic = -1
        for info in p.get_device_info_generator():
            if int(info.get("maxInputChannels", 0)) < 1:
                continue
            loopback = bool(info.get("isLoopbackDevice"))
            if loopback != (source == "system"):
                continue
            result.append({
                "index": int(info["index"]), "name": info["name"],
                "rate": int(info["defaultSampleRate"]),
                "channels": min(2, int(info["maxInputChannels"])),
                "loopback": loopback,
                "default": int(info["index"]) == (default_loop if loopback else default_mic),
            })
    return sorted(result, key=lambda d: (not d["loopback"], not d["default"], d["name"]))


def list_microphones():
    return list_devices("microphone")


def deepgram_url(config: ApiConfig, device: dict) -> str:
    return "wss://api.deepgram.com/v1/listen?" + urlencode({
        "model": config.deepgram_model, "language": config.language,
        "encoding": "linear16", "sample_rate": device["rate"],
        "channels": device["channels"], "smart_format": "true",
        "interim_results": "true", "endpointing": SPEEDS[config.speed][0],
        "utterance_end_ms": 1000, "vad_events": "true",
    })


class AudioCapture:
    def __init__(self, device: dict):
        self.device = device
        self.buffer: queue.Queue[bytes] = queue.Queue(maxsize=80)
        self.failed = threading.Event()
        self.p = None
        self.stream = None
        self.pa = audio_module()

    def callback(self, data, _frames, _time_info, status):
        if status:
            self.failed.set()
        try:
            self.buffer.put_nowait(data)
        except queue.Full:
            self.failed.set()
        return None, self.pa.paContinue

    def __enter__(self):
        self.p = self.pa.PyAudio()
        try:
            actual = self.p.get_device_info_by_index(self.device["index"])
            if actual["name"] != self.device["name"]:
                raise CoachError("Audio devices changed. Refresh devices and restart the coach.")
            self.stream = self.p.open(format=self.pa.paInt16, input=True,
                                      input_device_index=self.device["index"],
                                      channels=self.device["channels"], rate=self.device["rate"],
                                      frames_per_buffer=max(256, self.device["rate"] // 20),
                                      stream_callback=self.callback)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_args):
        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
        finally:
            if self.p is not None:
                self.p.terminate()


def level(data: bytes) -> int:
    if not data:
        return 0
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    rms = math.sqrt(sum(v * v for v in samples) / max(1, len(samples)))
    return min(100, int(rms / 32768 * 500))


class LiveSession:
    """One PCM source, one authenticated WebSocket, bounded audio queue.

    Call run() on a worker thread. emit(kind, value) must be thread-safe.
    Test and live modes use this identical audio/transport path.
    """

    def __init__(self, config: ApiConfig, device: dict, emit, duration: float | None = None, *, source="system"):
        self.source = source
        self.config, self.device, self.emit = config, device, emit
        self.duration = duration
        self.stop_event = threading.Event()
        self.ws = None

    def stop(self):
        self.stop_event.set()

    def run(self) -> str:
        if self.source not in ("system", "practice_microphone"):
            raise CoachError("Unknown audio source.")
        if self.source == "system" and not self.device.get("loopback"):
            raise CoachError("ALLY captures system audio only. Choose your meeting's speaker/headphone output.")
        if self.source == "practice_microphone" and self.device.get("loopback"):
            raise CoachError("Practice recording requires a microphone, not system audio.")
        if not self.config.deepgram_key.strip():
            raise CoachError("Paste your Deepgram API key first.")
        parser = Utterances()
        committed: list[str] = []
        receiver_error: list[Exception] = []
        remote_closed = threading.Event()
        finished = threading.Event()
        closing = threading.Event()
        receiver = None

        def receive():
            try:
                while not finished.is_set():
                    try:
                        message = self.ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not message:
                        if not closing.is_set():
                            raise CoachError("Deepgram disconnected. Stop and restart the session.")
                        break
                    event = json.loads(message)
                    for flag, stage in (("is_final", "deepgram_final"), ("speech_final", "speech_final")):
                        if event.get(flag):
                            self.emit("timing", (stage, time.monotonic()))
                    if event.get("type") == "Error":
                        raise CoachError("Deepgram rejected the stream. Check model and audio settings.")
                    if event.get("type") == "SpeechStarted":
                        self.emit("speaking", "")
                    final, interim, utterance = parser.accept(event)
                    if interim:
                        self.emit("hypothesis", " ".join(parser.pending + [interim]))
                    if final:
                        committed.append(final)
                        self.emit("final", final)
                    if interim:
                        self.emit("interim", interim)
                    if utterance:
                        self.emit("utterance", utterance)
            except Exception as exc:
                if not finished.is_set():
                    receiver_error.append(exc)
                    self.stop_event.set()
            finally:
                remote_closed.set()

        try:
            self.emit("status", "Connecting to Deepgram…")
            self.ws = websocket.create_connection(
                deepgram_url(self.config, self.device),
                header=[f"Authorization: Token {self.config.deepgram_key}"],
                timeout=10, enable_multithread=True,
            )
            self.ws.settimeout(1.5)
            receiver = threading.Thread(target=receive, daemon=True)
            receiver.start()
            with AudioCapture(self.device) as capture:
                start, last_audio, last_meter = time.monotonic(), time.monotonic(), 0.0
                self.emit("status", "Listening · " + self.device["name"])
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if self.duration is not None and now - start >= self.duration:
                        break
                    if capture.failed.is_set():
                        raise CoachError("Audio overflow or device error. Close heavy apps if this keeps happening.")
                    try:
                        chunk = capture.buffer.get(timeout=0.15)
                    except queue.Empty:
                        if now - last_audio > 3:
                            self.ws.send(json.dumps({"type": "KeepAlive"}))
                            last_audio = now
                        continue
                    if level(chunk) > 2:
                        self.emit("timing", ("last_speech", time.monotonic()))
                    self.ws.send_binary(chunk)
                    last_audio = now
                    if now - last_meter > 0.2:
                        self.emit("level", level(chunk))
                        last_meter = now
                # Drain service finals for bounded time; retain the end of the last question.
                closing.set()
                self.ws.send(json.dumps({"type": "Finalize"}))
                self.ws.send(json.dumps({"type": "CloseStream"}))
                remote_closed.wait(2.5)
            if receiver_error:
                raise receiver_error[0]
            return " ".join(committed)
        except websocket.WebSocketBadStatusException as exc:
            code = getattr(exc, "status_code", "unknown")
            raise CoachError(f"Deepgram connection rejected (HTTP {code}). Check key, model, language and billing.") from exc
        finally:
            finished.set()
            if self.ws is not None:
                self.ws.close(timeout=1)
            if receiver is not None:
                receiver.join(timeout=2)


class ContinuousSession:
    """Reconnect live capture without invoking the optional preflight test."""
    def __init__(self, config, device, emit):
        self.config, self.device, self.emit = config, device, emit
        self.stop_event = threading.Event()
        self.current = None

    def stop(self):
        self.stop_event.set()
        if self.current is not None:
            self.current.stop()

    def run(self):
        attempts = 0
        while not self.stop_event.is_set():
            self.current = LiveSession(self.config, self.device, self.emit)
            if self.stop_event.is_set():
                break
            started = time.monotonic()
            try:
                self.current.run()
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                # Invalid credentials/settings need a correction, never another test.
                if any(f"HTTP {code}" in str(exc) for code in (400, 401, 402, 403, 404, 422)) or "rejected the stream" in str(exc):
                    raise
            if self.stop_event.is_set():
                break
            attempts = 0 if time.monotonic() - started > 30 else attempts + 1
            delay = min(15, 2 ** min(attempts, 4))
            self.emit("status", f"Audio interrupted · reconnecting in {delay}s (no test needed)")
            self.emit("interim", "")
            if self.stop_event.wait(delay):
                break
        return ""
