import json
import threading

import pytest
import requests

from compass.core import ApiConfig, CoachError, GenerationError, PromptContext, stream_google
from compass.latency import LatencyLog
from compass.recovery import AttemptCancellation, fallback_models, relaxed_prompt, stream_with_fallback
from compass.transport import Cancellation


CONFIG = ApiConfig("private-google-key", "gemini-3.8-flash", "private-deepgram-key")
MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


class Response:
    def __init__(self, events=(), status=200):
        self.events, self.status_code, self.closed = events, status, False

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.closed = True
    def json(self): return {"error": "must not expose private-google-key"}
    def iter_content(self, **_):
        for item in self.events:
            if isinstance(item, Exception):
                raise item
            yield b"data: " + json.dumps(item).encode() + b"\n\n"


def event(text, finish="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


class Transport:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return response


def run(transport, **kwargs):
    return stream_with_fallback(CONFIG, "question", kwargs.pop("on_text", lambda _: None),
                                transport=transport, models=MODELS, **kwargs)


def test_success_accepts_any_format_no_extra_paid_call():
    transport = Transport(Response([event("A useful direct answer, without the requested headings.")]))
    assert "useful direct answer" in run(transport)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("failure", [Response(status=400), Response(status=403), Response(status=404), Response(status=429),
    Response(status=500), Response(status=503), Response(), Response([event("", "MAX_TOKENS")]),
    Response([event("cut off", None)]), Response([None]),
    requests.Timeout("secret"), requests.ConnectionError("secret")])
def test_failures_switch_model_and_relax_format(failure):
    transport = Transport(failure, Response([event("Complete recovery answer.")]))
    prompt = PromptContext("actual resume", "role").build("Question?", "history", "STAR", "Taglish", "Fast")
    seen = []
    result = stream_with_fallback(CONFIG, prompt, seen.append, transport=transport, models=MODELS,
                                  screenshot=b"png")
    assert result == "Complete recovery answer." and seen[-1] == result
    assert len(transport.calls) == 2
    assert "gemini-3.5-flash-lite" in transport.calls[1][0]
    first, second = (c[1]["json"] for c in transport.calls)
    assert second["contents"][0]["parts"][0] == first["contents"][0]["parts"][0]
    dynamic = json.loads(second["contents"][0]["parts"][1]["text"])
    assert dynamic["answer_style"].startswith("Quick")
    assert dynamic["answer_language"] == "Taglish" and dynamic["latest_question"] == "Question?"
    assert second["contents"][0]["parts"][-1] == first["contents"][0]["parts"][-1]
    assert "thinkingConfig" not in second["generationConfig"]
    assert "Never invent employers" in second["systemInstruction"]["parts"][0]["text"]
    assert json.loads(prompt[-1])["answer_style"] == "STAR"  # original is unchanged


def test_partial_replacement_uses_one_answer_not_concatenated():
    transport = Transport(Response([event("old partial", "MAX_TOKENS")]), Response([event("new answer")]))
    chunks = []
    assert run(transport, on_text=chunks.append) == "new answer"
    assert chunks[0] == "old partial" and chunks[-1] == "new answer"
    assert all("old partialnew answer" not in s for s in chunks)


def test_exhaustion_bounded_and_best_partial_is_explicit():
    transport = Transport(Response([event("A useful longer partial draft.", "MAX_TOKENS")]),
                          Response([event("short", "MAX_TOKENS")]), Response(status=503))
    states, attempts, chunks = [], [], []
    result = run(transport, progress=states.append, attempts=attempts, on_text=chunks.append)
    assert len(transport.calls) == 3 and len(attempts) == 3
    assert result.startswith("A useful longer partial draft.")
    assert result.count("Incomplete draft") == 1 and chunks[-1] == result
    assert states[-1]["state"] == "partial"
    assert len(set(c[0] for c in transport.calls)) == 3


def test_no_answer_shows_actionable_error_no_infinite_loop():
    transport = Transport(Response(status=503), Response(status=503), Response(status=503))
    with pytest.raises(CoachError, match="No answer after 3 attempt"):
        run(transport)
    assert len(transport.calls) == 3


@pytest.mark.parametrize("response", [Response(status=401),
    Response([{"promptFeedback": {"blockReason": "SAFETY"}}]), Response([event("", "SAFETY")])])
def test_auth_and_blocks_stop_without_fallback(response):
    transport = Transport(response)
    with pytest.raises(CoachError): run(transport)
    assert len(transport.calls) == 1


def test_explicit_invalid_key_not_retried_even_if_http_400():
    class InvalidKey(Response):
        def json(self):
            return {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}
    transport = Transport(InvalidKey(status=400))
    with pytest.raises(CoachError): run(transport)
    assert len(transport.calls) == 1


def test_disabled_stays_single_attempt():
    transport = Transport(Response(status=503))
    with pytest.raises(CoachError): run(transport, enabled=False)
    assert len(transport.calls) == 1


def test_catalog_filters_non_text_preview_and_ranks_lite_first():
    assert fallback_models("gemini-3.8-flash", MODELS + ["gemini-9-flash-image", "gemini-9-flash-tts",
        "gemini-9-flash-live", "gemini-9-flash-preview", "gemini-9-pro", "invalid"]) == [
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def test_catalog_discovery_once_and_single_available_model_simple_retry():
    catalog_calls, attempts = [], []
    def discover(*args, **kwargs):
        catalog_calls.append(kwargs)
        return [CONFIG.google_model]
    transport = Transport(Response(status=400), Response([event("usable")]))
    assert stream_with_fallback(CONFIG, "q", lambda _: None, transport=transport,
                                discover=discover, attempts=attempts) == "usable"
    assert len(catalog_calls) == 1 and len(attempts) == 2
    assert attempts[1]["simple_format"]
    assert transport.calls[0][0] == transport.calls[1][0]


def test_catalog_network_failure_uses_bounded_backup_models():
    def discover(*args, **kwargs): raise requests.Timeout()
    transport = Transport(Response(status=404), Response([event("recovered")]))
    assert stream_with_fallback(CONFIG, "q", lambda _: None, transport=transport, discover=discover) == "recovered"
    assert "gemini-3.5-flash-lite" in transport.calls[1][0]


def test_cancel_before_and_between_attempts_never_dispatches_more():
    cancel = Cancellation()
    cancel.set()
    transport = Transport()
    with pytest.raises(CoachError, match="cancelled"): run(transport, cancel=cancel)
    assert not transport.calls
    cancel = Cancellation()
    transport = Transport(Response(status=503))
    def progress(info):
        if info["state"] == "failed": cancel.set()
    with pytest.raises(CoachError, match="cancelled"): run(transport, cancel=cancel, progress=progress)
    assert len(transport.calls) == 1


def test_cancel_midstream_closes_bound_response_and_blocks_fallback():
    cancel = Cancellation()
    response = Response([event("opening", None), event("later")])
    transport = Transport(response)
    def chunk(text): cancel.set()
    with pytest.raises(CoachError, match="cancelled"): run(transport, cancel=cancel, on_text=chunk)
    assert response.closed and len(transport.calls) == 1


def test_attempt_cancellation_bind_race():
    parent = Cancellation()
    child = AttemptCancellation(parent)
    parent.set()
    response = Response()
    child.bind(response)
    assert child.is_set() and response.closed


def test_fake_clock_global_deadline_and_request_accounting():
    now = [0.]
    log = LatencyLog(clock=lambda: now[0])
    turn = log.new()
    def stream(*args, timing, **kwargs):
        timing("request_sent")
        now[0] += 23
        raise requests.Timeout()
    with pytest.raises(CoachError, match="No answer after 2"):
        stream_with_fallback(CONFIG, "q", lambda _: None, stream=stream, models=MODELS,
                             clock=lambda: now[0], attempts=turn.attempts,
                             timing=lambda stage: log.mark(turn, stage))
    report = log.report()
    assert report["requests_sent"] == 2 and report["fallback_attempts_sent"] == 1
    assert "private" not in log.dumps()


def test_watchdog_timeout_does_not_cancel_parent_and_can_recover():
    timers = []
    class Timer:
        def __init__(self, seconds, callback): self.seconds, self.callback = seconds, callback; timers.append(self)
        def start(self): pass
        def cancel(self): pass
    parent = Cancellation()
    calls = []
    def stream(config, prompt, receive, cancel, **kwargs):
        calls.append(config.google_model)
        if len(calls) == 1:
            response = Response()
            cancel.bind(response)
            timers[0].callback()
            raise requests.ConnectionError("socket closed")
        receive("complete")
        return "complete"
    assert stream_with_fallback(CONFIG, "q", lambda _: None, parent, stream=stream,
                                models=MODELS, timer_factory=Timer) == "complete"
    assert len(calls) == 2 and not parent.is_set()
    assert timers[0].seconds == 15


def test_relax_does_not_rewrite_reference_style_or_question():
    prompt = PromptContext('"answer_style":"STAR"', "role").build('literal "answer_style"', "", "STAR", "English", "Fast")
    simple = relaxed_prompt(prompt)
    assert simple[0] is prompt[0]
    assert json.loads(simple[1])["latest_question"] == json.loads(prompt[1])["latest_question"]
