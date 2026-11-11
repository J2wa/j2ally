"""Deterministic mocked timing experiment. No keys, network, Qt or audio needed.
Run from source root: python -m tools.latency_benchmark
Models a complete question with a usable interim 80 ms after last speech,
final arriving 500 ms after speech in both cases, cold TLS 180 ms, first body byte 300..680 ms,
first text SSE event 80 ms later and a 40 ms UI repaint.
"""
import json
from compass.core import ApiConfig, stream_google
from compass.latency import LatencyLog
from compass.turns import TurnGate, adaptive_wait, SPEEDS


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now
    def advance(self, delta): self.now += delta


def measure(optimized):
    clock = Clock()
    log = LatencyLog(clock)
    for index in range(20):
        origin = clock()
        gate = TurnGate()
        turn = log.new(speculative=optimized)
        log.mark(turn, 'last_speech')
        question = 'How do you test software?'
        final_at = origin + .5
        if optimized:
            # Exercise the same gate and silence value as the UI. An interim receipt
            # conservatively resets silence, so trigger is 80+280 ms after speech.
            clock.advance(.08)
            clock.advance(SPEEDS['Fast'][1] / 1000)
            assert gate.speculate(question, SPEEDS['Fast'][1], 'Fast')
        else:
            clock.now = final_at
            clock.advance(.45)
        log.mark(turn, 'auto_triggered')
        final_seen = False
        def finalize_if_due():
            nonlocal final_seen
            if not final_seen and clock() >= final_at:
                final_seen = True
                log.mark(turn, 'deepgram_final', final_at)
                log.mark(turn, 'speech_final', final_at)
                assert gate.final(question) == ('keep' if optimized else 'start')
        class Response:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def iter_content(self, **kwargs):
                clock.advance(.3 + index * .02)
                finalize_if_due()
                yield b'data: '
                clock.advance(.08)
                finalize_if_due()
                yield b'{"candidates":[{"content":{"parts":[{"text":"I test incrementally."}]}}]}\n'
        class Transport:
            def post(self, *args, **kwargs):
                if not optimized:
                    clock.advance(.18)  # explicit modeled cold TLS cost, not measured network
                return Response()
        def render(text):
            clock.advance(.04)
            log.mark(turn, 'first_render')
        stream_google(ApiConfig('mock', 'gemini-2.5-flash-lite', 'mock'), question, render,
                      transport=Transport(), timing=lambda stage: log.mark(turn, stage))
        finalize_if_due()
        clock.advance(1)
    return log.report()


def report():
    return {'kind': 'deterministic mocked timings; not a live latency claim',
            'assumptions': __doc__, 'before': measure(False), 'after_fast': measure(True)}


if __name__ == '__main__':
    print(json.dumps(report(), indent=2))
