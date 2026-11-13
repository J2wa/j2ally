"""Bounded live-answer recovery. No Qt, extra credentials or hidden retry loops."""
from dataclasses import replace
import json
import re
import threading
import time

import requests

from .core import CoachError, GenerationError, list_google_models, stream_google
from .transport import Cancellation

MAX_ATTEMPTS = 3
TOTAL_SECONDS = 45
ATTEMPT_SECONDS = 15
# Used only if the account's model catalog cannot be loaded. Each is tried once.
BACKUP_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")


class AttemptCancellation(Cancellation):
    """An attempt timeout closes its socket without cancelling the whole answer."""

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    def is_set(self):
        return super().is_set() or bool(self.parent and self.parent.is_set())

    def bind(self, response):
        super().bind(response)
        if hasattr(self.parent, "bind"):
            self.parent.bind(response)
        if self.is_set():
            response.close()


def fallback_models(selected, models):
    """Prefer stable text Flash-Lite then Flash, newest versions first."""
    def rank(model):
        version = re.match(r"gemini-(\d+)(?:\.(\d+))?", model)
        return ("-lite" not in model, -int(version[1]), -int(version[2] or 0))
    candidates = {m.removeprefix("models/").strip() for m in models if isinstance(m, str)}
    candidates = [m for m in candidates if m != selected and
                  re.fullmatch(r"gemini-\d+(?:\.\d+)?-flash(?:-lite)?", m)]
    return sorted(candidates, key=rank)[:MAX_ATTEMPTS - 1]


def relaxed_prompt(prompt):
    """Change only the actual style field, leaving all reference data intact."""
    parts = list(prompt) if isinstance(prompt, list) else [prompt]
    for index in range(len(parts) - 1, -1, -1):
        try:
            data = json.loads(parts[index])
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and "answer_style" in data:
            data["answer_style"] = "Quick: complete direct answer; formatting is optional"
            parts[index] = json.dumps(data, ensure_ascii=False)
            break
    return parts if isinstance(prompt, list) else parts[0]


def stream_with_fallback(config, prompt, on_text, cancel=None, *, enabled=True,
                         models=(), screenshot=None, timing=None, transport=None,
                         progress=None, attempts=None, clock=time.monotonic,
                         stream=None, discover=None, timer_factory=threading.Timer):
    """One primary plus at most two simple-format attempts; accept any usable format.

    Partial drafts remain visible until replacement text arrives. Replacements replace
    the same answer entry. All attempts failing retains the longest partial with a warning.
    Cancellation, validation/auth errors and provider blocks never trigger fallbacks.
    """
    stream = stream or stream_google
    if not enabled:
        return stream(config, prompt, on_text, cancel, screenshot=screenshot,
                      timing=timing, transport=transport)
    selected = config.google_model.removeprefix("models/").strip()
    if not config.google_key or not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", selected):
        raise CoachError("Paste a Google AI Studio key and select a Gemini model.")
    if screenshot and len(screenshot) > 12 * 1024 * 1024:
        raise CoachError("Screenshot is too large. Use a smaller screen resolution.")
    deadline = clock() + TOTAL_SECONDS
    attempts = attempts if attempts is not None else []
    plans = [(selected, False)]
    best = ""
    last_kind = "unavailable"

    def cancelled():
        if cancel is not None and cancel.is_set():
            raise CoachError("Answer cancelled.")

    def announce(state, record):
        if progress:
            progress(dict(record, state=state))

    for index in range(MAX_ATTEMPTS):
        cancelled()
        remaining = deadline - clock()
        if index >= len(plans) or remaining <= 0:
            break
        model, simple = plans[index]
        record = {"number": index + 1, "model": model, "simple_format": simple,
                  "timestamps": {}, "outcome": "requesting"}
        attempts.append(record)
        announce("requesting", record)
        child = AttemptCancellation(cancel)
        seconds = min(ATTEMPT_SECONDS, remaining)
        watchdog = timer_factory(seconds, child.set)
        watchdog.daemon = True
        def receive(text):
            nonlocal best
            cancelled()
            if child.is_set() or clock() >= deadline:
                raise GenerationError("Answer attempt timed out.", "timeout")
            if len(text.strip()) > len(best.strip()):
                best = text
            on_text(text)

        def stamp(stage):
            record["timestamps"].setdefault(stage, clock())
            if timing:
                timing(stage)

        watchdog.start()
        try:
            result = stream(replace(config, google_model=model), relaxed_prompt(prompt) if simple else prompt,
                            receive, child, screenshot=screenshot, transport=transport,
                            timing=stamp, simple=simple, strict=True,
                            timeout=(min(4, seconds / 2), min(8, seconds / 2)))
            cancelled()
            if child.is_set() or clock() >= deadline:
                raise GenerationError("Answer attempt timed out.", "timeout")
            if not result.strip():
                raise GenerationError("Google returned no answer.", "empty")
            record["outcome"] = "complete"
            announce("complete", record)
            return result
        except (GenerationError, requests.RequestException, CoachError) as exc:
            if cancel is not None and cancel.is_set():
                record.update(outcome="cancelled", reason="user_cancelled")
                announce("cancelled", record)
            cancelled()
            if child.is_set():
                kind, recoverable = "timeout", True
            elif isinstance(exc, GenerationError):
                kind, recoverable = exc.kind, exc.recoverable
            elif isinstance(exc, requests.RequestException):
                kind, recoverable = "network", True
            else:
                # Invalid local input is not repaired by paying another model.
                raise
            record.update(outcome="failed", reason=kind)
            last_kind = kind
            announce("failed", record)
            if not recoverable:
                on_text("")
                raise
        finally:
            watchdog.cancel()

        cancelled()
        if index == 0:
            catalog = list(models)
            if not catalog and deadline - clock() > 0:
                lookup = AttemptCancellation(cancel)
                lookup_seconds = min(6, deadline - clock())
                lookup_timer = timer_factory(lookup_seconds, lookup.set)
                lookup_timer.daemon = True
                lookup_timer.start()
                try:
                    catalog = (discover or list_google_models)(config.google_key, transport=transport,
                        cancel=lookup, timeout=(min(3, lookup_seconds / 2), min(3, lookup_seconds / 2)), max_pages=3)
                except (CoachError, requests.RequestException):
                    catalog = list(BACKUP_MODELS)
                finally:
                    lookup_timer.cancel()
                cancelled()
            alternatives = fallback_models(selected, catalog)
            # Single-model accounts still get one attempt with relaxed formatting/settings.
            if alternatives:
                plans.extend((m, True) for m in alternatives)
            else:
                plans.append((selected, True))

    cancelled()
    final = {"number": len(attempts), "model": attempts[-1]["model"] if attempts else selected,
             "reason": last_kind}
    if best.strip():
        result = best + "\n\n*Incomplete draft: automatic fallback could not finish this answer. Check it before use; try again manually.*"
        on_text(result)
        announce("partial", final)
        return result
    announce("exhausted", final)
    raise CoachError(f"No answer after {len(attempts)} attempt(s) ({last_kind}). "
                     "Check your internet connection, model access and Google quota in API & audio.")
