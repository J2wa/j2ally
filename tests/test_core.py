from dataclasses import replace
import json
import threading

import pytest

from compass.core import ApiConfig, CoachError, Preflight, SYSTEM_PROMPT, Utterances, build_prompt, checked_json, list_google_models, read_context, safe_error, stream_google


@pytest.fixture
def config():
    return ApiConfig("google-secret", "gemini-test-flash", "deepgram-secret")


class Response:
    def __init__(self, data=None, lines=None, status=200):
        self.status_code, self.data, self.lines = status, data, lines or []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def json(self):
        return self.data

    def iter_lines(self, **_):
        yield from self.lines


def event(text, **extra):
    return b"data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}, **extra}]}).encode()


def test_real_generation_shape_and_incremental_text(monkeypatch, config):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(lines=[b": comment", b"", event("Hello "), event("candidate.")])
    monkeypatch.setattr("compass.core.requests.post", post)
    chunks = []
    assert stream_google(config, "question", chunks.append) == "Hello candidate."
    assert chunks == ["Hello ", "Hello candidate."]
    url, kwargs = calls[0]
    assert "google-secret" not in url
    assert kwargs["headers"] == {"x-goog-api-key": "google-secret"}
    assert kwargs["params"] == {"alt": "sse"}
    assert kwargs["json"]["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "question"


def test_do_not_render_thought_parts(monkeypatch, config):
    body = {"candidates": [{"content": {"parts": [{"thought": True, "text": "private reasoning"}, {"text": "answer"}]}}]}
    monkeypatch.setattr("compass.core.requests.post", lambda *_a, **_k: Response(lines=[b"data: " + json.dumps(body).encode()]))
    assert stream_google(config, "q", lambda _: None) == "answer"


@pytest.mark.parametrize("lines", [[], [b"data: broken-json"], [b'data: {"promptFeedback":{"blockReason":"SAFETY"}}'], [b'data: {"error":{"message":"bad"}}'], [event("", finishReason="SAFETY")]])
def test_generation_failures(monkeypatch, config, lines):
    monkeypatch.setattr("compass.core.requests.post", lambda *_a, **_k: Response(lines=lines))
    with pytest.raises(CoachError):
        stream_google(config, "q", lambda _: None)


def test_cancel_generation(monkeypatch, config):
    monkeypatch.setattr("compass.core.requests.post", lambda *_a, **_k: Response(lines=[event("ignored")]))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CoachError, match="cancelled"):
        stream_google(config, "q", lambda _: pytest.fail("cancelled text rendered"), cancel)


def test_token_limit_visible(monkeypatch, config):
    monkeypatch.setattr("compass.core.requests.post", lambda *_a, **_k: Response(lines=[event("Partial", finishReason="MAX_TOKENS")]))
    assert "Output limit reached" in stream_google(config, "q", lambda _: None)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 503])
def test_http_errors_never_show_raw_server_body(status):
    with pytest.raises(CoachError, match=f"HTTP {status}") as caught:
        checked_json(Response(data={"error": "secret key in body"}, status=status), "Google")
    assert "secret key" not in str(caught.value)


def test_model_discovery_paginates_and_filters(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return Response({"models": [{"name": "models/gemini-test", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}], "nextPageToken": "next"})
        return Response({"models": [{"name": "models/gemini-image", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/gemini-other", "supportedGenerationMethods": ["generateContent"]}]})
    monkeypatch.setattr("compass.core.requests.get", get)
    assert list_google_models("key") == ["gemini-test", "gemini-other"]
    assert calls[1]["params"]["pageToken"] == "next"


def test_preflight_is_bound_to_current_settings(config):
    device = {"index": 2, "name": "Headphones", "rate": 48000, "channels": 2}
    ready = Preflight(config.google_signature(), config.audio_signature(device))
    assert ready.ready(config, device)
    assert not ready.ready(replace(config, google_key="new"), device)
    assert not ready.ready(replace(config, google_model="gemini-other"), device)
    assert not ready.ready(replace(config, deepgram_key="new"), device)
    assert not ready.ready(replace(config, deepgram_model="other"), device)
    assert not ready.ready(replace(config, language="multi"), device)
    assert not ready.ready(config, {**device, "rate": 44100})
    assert not ready.ready(config, None)
    assert not Preflight().ready(config, device)
    assert "google-secret" not in repr(config)
    assert "deepgram-secret" not in repr(config)


def test_reference_data_is_delimited_and_bounded():
    prompt = build_prompt("True resume", "Required skill X", "Follow-up?", "x" * 20000, "Short", "Taglish")
    data = json.loads(prompt)
    assert data["candidate_resume_and_notes"] == "True resume"
    assert data["job_description"] == "Required skill X"
    assert len(data["recent_transcript"]) == 6000
    assert data["answer_language"] == "Taglish"
    assert "Never invent" in SYSTEM_PROMPT
    for resume, job, question in (("", "j", "q"), ("r", "", "q"), ("r", "j", ""), ("r" * 80001, "j", "q")):
        with pytest.raises(CoachError):
            build_prompt(resume, job, question, "", "Short", "English")


def test_redacts_keys_and_authorization():
    message = safe_error(Exception("key ABC / xyz Authorization: Token whatever"), "ABC", "xyz")
    assert "ABC" not in message and "xyz" not in message and "whatever" not in message


def result(text, start=0, final=True, speech_final=False, **extra):
    return {"type": "Results", "start": start, "duration": 1, "is_final": final, "speech_final": speech_final,
            "channel": {"alternatives": [{"transcript": text}]}, **extra}


def test_interim_final_endpoint_assembly():
    parser = Utterances()
    assert parser.accept(result("Tell", final=False)) == ("", "Tell", "")
    first = result("Tell me", start=0)
    assert parser.accept(first) == ("Tell me", "", "")
    assert parser.accept(first) == ("", "", "")  # duplicate service event
    assert parser.accept(result("about yourself?", start=1, speech_final=True)) == ("about yourself?", "", "Tell me about yourself?")
    assert parser.accept({"type": "UtteranceEnd"}) == ("", "", "")
    assert parser.accept(result("Second turn", start=2))[0] == "Second turn"
    assert parser.accept({"type": "UtteranceEnd"})[2] == "Second turn"


def test_empty_endpoint_flushes_pending_and_finalize_works():
    parser = Utterances()
    parser.accept(result("Pending sentence"))
    assert parser.accept(result("", speech_final=True))[2] == "Pending sentence"
    assert parser.accept(result("End", start=3, from_finalize=True))[2] == "End"


def test_context_import_plain_text_and_docx_tables(tmp_path):
    text = tmp_path / "resume.txt"
    text.write_text("\ufeffCandidate\nPython", encoding="utf-8")
    assert read_context(str(text)) == "Candidate\nPython"
    from docx import Document
    doc = Document()
    doc.add_paragraph("Candidate name")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Python"
    path = tmp_path / "resume.docx"
    doc.save(path)
    imported = read_context(str(path))
    assert "Candidate name" in imported and "Skill | Python" in imported


def test_blank_pdf_and_overlong_text_rejected(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.write(path)
    with pytest.raises(CoachError, match="OCR"):
        read_context(str(path))
    text = tmp_path / "huge.txt"
    text.write_text("a" * 80001)
    with pytest.raises(CoachError, match="80,000"):
        read_context(str(text))


def test_screenshot_inline_image_with_job_context(monkeypatch, config):
    import base64
    seen = []
    def post(_url, **kwargs):
        seen.append(kwargs['json'])
        return Response(lines=[event('Screenshot answer')])
    monkeypatch.setattr('compass.core.requests.post', post)
    png = b'\x89PNG\r\n\x1a\nexample'
    prompt = build_prompt('Resume', 'Job description', 'Read screen', '', 'Quick', 'English')
    stream_google(config, prompt, lambda _: None, screenshot=png)
    parts = seen[0]['contents'][0]['parts']
    assert json.loads(parts[0]['text'])['job_description'] == 'Job description'
    assert parts[1]['inlineData']['mimeType'] == 'image/png'
    assert base64.b64decode(parts[1]['inlineData']['data']) == png


def test_low_latency_config_is_model_specific():
    from compass.core import fast_generation_config
    assert fast_generation_config('gemini-2.5-flash')['thinkingConfig'] == {'thinkingBudget': 0}
    assert fast_generation_config('gemini-3.8-flash')['thinkingConfig'] == {'thinkingLevel': 'low'}
    assert 'thinkingConfig' not in fast_generation_config('gemini-2.5-pro')
    assert 'thinkingConfig' not in fast_generation_config('gemini-future')
