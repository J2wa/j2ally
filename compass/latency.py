"""Local monotonic timing only. Reports contain no speech, prompts or keys."""
from dataclasses import dataclass, field
import json
import math
import statistics
import time


def percentiles(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "median_ms": None, "p95_ms": None}
    return {"count": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[math.ceil(.95 * len(values)) - 1], 2)}


@dataclass
class TurnTiming:
    id: int
    source: str
    stamps: dict = field(default_factory=dict)
    cancelled: bool = False
    speculative: bool = False


class LatencyLog:
    def __init__(self, clock=time.monotonic, window=100):
        self.clock, self.window = clock, window
        self.turns = []
        self.speculative_cancelled = 0

    def new(self, source="audio", speculative=False):
        turn = TurnTiming(len(self.turns) + 1, source, speculative=speculative)
        self.turns.append(turn)
        return turn

    def mark(self, turn, stage, at=None):
        if turn is not None:
            turn.stamps.setdefault(stage, self.clock() if at is None else at)

    def first_words(self, turn):
        s = turn.stamps
        origin = s.get("last_speech", s.get("auto_triggered"))
        if origin is None or "first_render" not in s:
            return None
        return max(0, (s["first_render"] - origin) * 1000)

    def cancel(self, turn):
        if turn and not turn.cancelled:
            turn.cancelled = True
            if turn.speculative:
                self.speculative_cancelled += 1

    def report(self):
        eligible = [t for t in self.turns if not t.cancelled and self.first_words(t) is not None]
        return {"clock": "monotonic seconds", "p95_method": "nearest rank", "rolling_window": self.window,
                "rolling": percentiles([self.first_words(t) for t in eligible[-self.window:]]),
                "speculative_requests_cancelled": self.speculative_cancelled,
                "requests_scheduled": len(self.turns),
                "requests_sent": sum("request_sent" in t.stamps for t in self.turns),
                "turns": [{"id": t.id, "source": t.source, "speculative": t.speculative,
                           "cancelled": t.cancelled, "timestamps": t.stamps,
                           "time_to_first_words_ms": self.first_words(t)} for t in self.turns]}

    def dumps(self):
        return json.dumps(self.report(), indent=2)
