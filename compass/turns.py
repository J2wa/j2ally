"""Pure turn policy; no Qt, audio hardware or provider calls."""
import re
from difflib import SequenceMatcher

SPEEDS = {"Fast": (250, 280, 0, 650), "Balanced": (400, 300, 100, 850),
          "Careful": (650, 300, 300, 1200)}


def words(text):
    return re.findall(r"[\w']+", text.lower())


def unfinished(text):
    tokens = words(text)
    return not tokens or tokens[-1] in {"and", "or", "but", "because", "if", "when", "so", "with", "to", "the", "a", "of", "for", "that", "which"} or text.rstrip().endswith((",", ":", "—"))


def is_question(text):
    tokens = words(text)
    if len(tokens) < 3 or unfinished(text):
        return False
    normalized = " ".join(tokens)
    if normalized.startswith(("thanks", "thank you", "hello", "hi everyone", "good morning", "good afternoon")):
        return False
    if re.match(r"^(?:how are you|how is your day|can you hear me|can you see my screen|are you there|is my (?:mic|microphone|audio)|do you hear me)\b", normalized):
        return False
    return text.rstrip().endswith("?") or bool(re.match(
        r"^(?:(?:so|okay|ok) )?(?:what|why|how|when|where|who|which|can you|could you|would you|do you|did you|have you|are you|will you|tell me|describe|explain|walk me|give me)\b", normalized))


def adaptive_wait(text, speed="Fast"):
    _, _, clear, incomplete = SPEEDS[speed]
    return incomplete if unfinished(text) else clear if is_question(text) else max(clear, 450)


def materially_differs(before, after):
    a, b = words(before), words(after)
    if a == b:
        return False
    # Preserve meaning changes even if character edit distance is tiny.
    semantic = {"not", "never", "no", "without"}
    if (set(a) & semantic) != (set(b) & semantic):
        return True
    if re.findall(r"\d+", before) != re.findall(r"\d+", after):
        return True
    if len(b) - len(a) >= 2:
        return True
    return SequenceMatcher(None, a, b).ratio() < .92


class TurnGate:
    def __init__(self):
        self.sent = ""
        self.finalized = False
        self.suppressed = False

    def speculate(self, text, silence_ms, speed):
        if self.sent or self.finalized or self.suppressed or speed == "Careful":
            return False
        if silence_ms < SPEEDS[speed][1] or not is_question(text):
            return False
        self.sent = text
        return True

    def final(self, text):
        if self.suppressed:
            self.finalized = True
            return "skip"
        if self.finalized:
            return "duplicate"
        self.finalized = True
        if not self.sent:
            return "start"
        return "restart" if materially_differs(self.sent, text) else "keep"
