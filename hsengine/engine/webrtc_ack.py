"""Immediate spoken ack while Ripley works. Combinatorial, not a catchphrase.

Kyutai TTS of a short line — no Cerebras round. Humans notice a 3-phrase
cycle; this space is large enough that repeats are rare in a session.
"""
from __future__ import annotations

import random
import re
import threading
from typing import Any

_OPEN = (
    "Yeah",
    "Mm",
    "Right",
    "Okay",
    "Got it",
    "Sure",
    "Alright",
    "On it",
    "Heard",
    "Copy",
    "Yep",
    "Okay yeah",
    "Mm-hm",
    "Fair",
    "Good",
    "Noted",
    "With you",
    "I'm here",
    "Stay with me",
    "One beat",
    "Hang on",
    "Give me a second",
    "Give me a minute",
    "Hold the floor",
    "Don't go anywhere",
    "Sit tight",
    "Hold on",
    "Wait one",
    "Just a second",
    "Two seconds",
    "Bear with me",
    "Let me look",
    "Let me pull that",
    "Let me see",
    "I'll take that",
    "Taking that",
    "Working it",
    "On the board",
    "On the tape",
    "In the lattice",
)

_MIDDLE = (
    "looking",
    "pulling that up",
    "digging",
    "checking",
    "on the lattice",
    "on the tape",
    "in the filings",
    "in the numbers",
    "at the figure",
    "at the chord",
    "at the lanes",
    "through the 8-K",
    "through the Form 4s",
    "across those names",
    "under the hood",
    "on this thread",
    "at what's moving",
    "at the density",
    "at SLB's lane",
    "at the heatmap",
    "at the timeline",
    "one more look",
    "a second pass",
    "the interesting bit",
    "the real driver",
    "the shadow not the object",
    "what the tape is doing",
    "what the filings say",
    "where the weight is",
    "which lane is busy",
    "how this sits",
    "how this reads",
    "what to put on glass",
    "whether the figure still matches",
    "the next useful cut",
    "a cleaner angle",
    "the part that isn't boilerplate",
)

_TAIL = (
    "hold on",
    "hold tight",
    "stay with me",
    "give me a beat",
    "give me a second",
    "don't go anywhere",
    "one moment",
    "almost",
    "working",
    "on it",
    "coming",
    "hang on",
    "wait one",
    "I've got this",
    "leave it with me",
    "I'll bring it back",
    "I'll put it on the feed",
    "I'll speak when it's real",
    "won't be long",
    "stay put",
    "keep talking if you want",
    "interrupt me if I'm wrong",
    "this won't take long",
    "let me finish this cut",
    "then I'll talk",
    "then it's on glass",
    "then we can look together",
)

_TEMPLATES = (
    "{open}. {middle}.",
    "{open} — {middle}.",
    "{open}. {tail}.",
    "{open} — {tail}.",
    "{middle}. {tail}.",
    "{open}. {middle} — {tail}.",
    "{open}, {middle}.",
    "{open}. {middle}, {tail}.",
    "{open} — {middle}. {tail}.",
    "{middle}. {open}, {tail}.",
)

_HOOK_RE = re.compile(
    r"\b(SLB|HAL|BKR|NOV|NWL|CRM|DOW|MU|8-K|Form\s*4|filings?|chord|"
    r"heatmap|timeline|density|lattice|tape|Schlumberger|Halliburton|"
    r"Baker|oilfield)\b",
    re.IGNORECASE,
)

_recent: list[str] = []
_mu = threading.Lock()
_RECENT = 48

# Open × middle × tail × templates, minus collisions, is thousands.
assert len(_OPEN) * len(_MIDDLE) * len(_TAIL) * 3 > 1000


def _hook(utterance: str) -> str:
    found = _HOOK_RE.findall(utterance or "")
    if not found:
        return ""
    token = found[-1]
    token = re.sub(r"\s+", " ", token).strip()
    if len(token) > 16:
        return ""
    return token


def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    text = text.replace("..", ".")
    text = re.sub(r"\s+([.,—])", r"\1", text)
    text = re.sub(r"([.,]){2,}", r"\1", text)
    if text and text[-1] not in ".!?":
        text += "."
    # Title-case first char if we started with a mid-sentence fragment
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    words = text.split()
    if len(words) > 14:
        text = " ".join(words[:14]).rstrip(".,") + "."
    return text


def ack_line(utterance: str = "", *, rng: random.Random | None = None) -> str:
    """One short spoken ack. Combinatorial; avoids the last few lines."""
    rng = rng or random.Random()
    hook = _hook(utterance)
    middles = list(_MIDDLE)
    if hook:
        extra = (
            f"on {hook}",
            f"looking at {hook}",
            f"pulling {hook}",
            f"in {hook}" if hook.lower() not in {"8-k", "form 4"} else f"on that {hook}",
            f"the {hook} cut",
        )
        middles.extend(extra)
    for _ in range(24):
        open_ = rng.choice(_OPEN)
        middle = rng.choice(middles)
        tail = rng.choice(_TAIL)
        if middle.lower() in open_.lower() or tail.lower() in open_.lower():
            continue
        if tail.lower() in middle.lower():
            continue
        line = rng.choice(_TEMPLATES).format(open=open_, middle=middle, tail=tail)
        line = _clean(line)
        if len(line) < 8:
            continue
        with _mu:
            if line in _recent:
                continue
            _recent.append(line)
            del _recent[:-_RECENT]
        return line
    return _clean(f"{rng.choice(_OPEN)}. {rng.choice(_TAIL)}.")


def space_size() -> int:
    return len(_OPEN) * len(_MIDDLE) * len(_TAIL) * len(_TEMPLATES)
