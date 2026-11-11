import json
import pytest
from compass.latency import LatencyLog, percentiles
from compass.turns import TurnGate, adaptive_wait, is_question, materially_differs
from compass.core import PromptContext, stream_google, ApiConfig
from compass.transport import Cancellation, GeminiTransport


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


def test_latency_stats_fake_clock():
    clock = Clock()
    log = LatencyLog(clock, window=3)
    for delay in (.1, .2, .3, .4):
        t = log.new()
        log.mark(t, 'last_speech')
        clock.advance(delay)
        log.mark(t, 'first_render')
    assert log.report()['rolling'] == {'count': 3, 'median_ms': 300., 'p95_ms': 400.}
    log.cancel(t)
    assert log.report()['rolling']['median_ms'] == 200.
    assert percentiles([])['p95_ms'] is None
    spec = log.new(speculative=True)
    log.cancel(spec); log.cancel(spec)
    assert log.speculative_cancelled == 1
    assert 'resume' not in log.dumps()


@pytest.mark.parametrize('speed,question,incomplete', [('Fast', 0, 650), ('Balanced', 100, 850), ('Careful', 300, 1200)])
def test_adaptive_wait(speed, question, incomplete):
    assert adaptive_wait('How do you test software?', speed) == question
    assert adaptive_wait('How do you test software and', speed) == incomplete
    assert adaptive_wait('Some statement.', speed) >= 450


@pytest.mark.parametrize('text', ['Thanks for your time.', 'Good morning everyone', 'I worked with Python.', 'How do you work and', 'Hi everyone?', 'How are you today?', 'Can you hear me clearly?'])
def test_statements_not_questions(text):
    assert not is_question(text)


def test_speculation_kept_or_restarted():
    gate = TurnGate()
    assert not gate.speculate('How do you test software?', 250, 'Fast')
    assert gate.speculate('How do you test software?', 280, 'Fast')
    assert not gate.speculate('How do you test software?', 400, 'Fast')
    assert gate.final('How do you test software') == 'keep'
    assert gate.final('How do you test software') == 'duplicate'
    gate = TurnGate()
    gate.speculate('How do you test software?', 300, 'Fast')
    assert gate.final('How do you test software when there are no specifications?') == 'restart'
    assert materially_differs('Do you use Python?', 'Do you not use Python?')
    assert materially_differs('Explain Python 2?', 'Explain Python 3?')


def test_prompt_prefix_and_fast_history():
    context = PromptContext('real resume', 'job')
    first = context.build('Question?', '\n'.join(str(i) for i in range(20)), 'Quick', 'English', 'Fast')
    second = context.build('Follow up?', 'different', 'Detailed', 'Taglish', 'Careful')
    assert first[0] is second[0]
    assert json.loads(first[1])['recent_transcript'] == '17\n18\n19'


def test_cancel_bind_race():
    cancel = Cancellation()
    cancel.set()
    class Response:
        closed = False
        def close(self): self.closed = True
    response = Response()
    cancel.bind(response)
    assert cancel.is_set() and response.closed


def test_transport_reuses_session_and_disables_retries():
    class Session:
        def mount(self, prefix, adapter): assert adapter.max_retries.total == 0
        def post(self, *a, **kw): return id(self)
    session = Session()
    transport = GeminiTransport(session)
    assert transport.post('url') == transport.post('url') == id(session)


def test_byte_timing_precedes_complete_sse_line():
    clock = Clock()
    log = LatencyLog(clock)
    t = log.new()
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def iter_content(self, **kw):
            clock.advance(.1)
            yield b'data: '
            clock.advance(.2)
            yield b'{"candidates":[{"content":{"parts":[{"text":"Yes"}]}}]}\n'
    class Transport:
        def post(self, *a, **kw): return Response()
    stream_google(ApiConfig('key', 'gemini-2.5-flash', 'd'), 'question', lambda _: log.mark(t, 'first_render'),
                  transport=Transport(), timing=lambda stage: log.mark(t, stage))
    assert t.stamps['first_response_byte'] == pytest.approx(.1)
    assert t.stamps['first_render'] == pytest.approx(.3)


def test_reproducible_mocked_before_after():
    from tools.latency_benchmark import report
    result = report()
    assert result['before']['rolling'] == {'count': 20, 'median_ms': 1740., 'p95_ms': 1910.}
    assert result['after_fast']['rolling'] == {'count': 20, 'median_ms': 970., 'p95_ms': 1140.}
    assert all(len(t['timestamps']) == 8 for t in result['after_fast']['turns'])


def test_idle_prewarm_is_non_generation_and_throttled():
    import threading
    clock = Clock()
    called = []
    done = threading.Event()
    class Response:
        content = b'not found'
        def __enter__(self): return self
        def __exit__(self, *_): done.set()
    class Session:
        def mount(self, *args): pass
        def get(self, url, **kwargs):
            called.append((url, kwargs))
            return Response()
    transport = GeminiTransport(Session(), clock)
    transport.prewarm()
    assert done.wait(1)
    # join via lock-free completion event before asking again
    import time
    limit = time.monotonic() + 1
    while transport.warming and time.monotonic() < limit:
        time.sleep(.001)
    transport.prewarm()
    assert len(called) == 1
    assert called[0][0] == 'https://generativelanguage.googleapis.com/'
    assert 'headers' not in called[0][1]
    clock.advance(46)
    done.clear()
    transport.prewarm()
    assert done.wait(1)
    assert len(called) == 2
