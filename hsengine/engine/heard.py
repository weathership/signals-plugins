"""A fresh one-line heard-you, spoken while the real lookup runs.

Not a phrase list. The line has to reuse something they just said, or it
is discarded and tried once more. A stock ack is worse than silence.
"""
from __future__ import annotations

import re

_STOCK = (
    "on it",
    "got it",
    "sure thing",
    "hang on",
    "hold on",
    "one sec",
    "one second",
    "let me look",
    "let me see",
    "let me pull",
    "give me a sec",
    "give me a second",
    "absolutely",
    "of course",
    "no problem",
    "will do",
    "you bet",
    "copy that",
    "heard",
    "okay",
    "ok",
)

_STOP = frozenset(
    """
    a an the and or but if so to of in on for with from at by as
    oh yeah yes yep no tell me about that this those these what
    how when where who why just like want please can could would
    """.split()
)


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return [w for w in words if len(w) > 2 and w not in _STOP]


def _is_stock(blob: str) -> bool:
    words = [w.strip(".,!?") for w in blob.split()]
    joined = " ".join(words)
    if joined in _STOCK:
        return True
    for phrase in _STOCK:
        n = len(phrase.split())
        if n <= len(words) and " ".join(words[:n]) == phrase:
            return True
    return False


def line_is_fresh(utterance: str, line: str) -> bool:
    """True only if the line uses their words and does not open as a stock ack."""
    blob = " ".join((line or "").lower().split())
    if not blob or len(blob.split()) > 18:
        return False
    if _is_stock(blob):
        return False
    keys = content_words(utterance)
    if not keys:
        return True
    return any(key in blob for key in keys)


def repeats_previous_turn(previous: str, candidate: str) -> bool:
    """A long reply that copies the last spoken turn is not an answer.

    Short agreements ("yeah", "right") may repeat. The failure we saw was
    the whole previous monologue spoken again, unchanged, after a new question.
    """
    prev = " ".join((previous or "").split())
    cur = " ".join((candidate or "").split())
    if len(prev) < 80 or len(cur) < 80:
        return False
    if cur == prev:
        return True
    n = min(240, len(prev), len(cur))
    return prev[:n] == cur[:n]


def heard_prompts(utterance: str, *, rejected: str = "") -> tuple[str, str]:
    said = " ".join((utterance or "").split())
    system = (
        "You are Ripley on a live call. They just asked for something. "
        "You are about to go do the work. One short sentence, under twelve words, "
        "then stop. Show you heard the specific thing and that you are going. "
        "Do not answer it yet. Do not greet. Do not ask a question. "
        "A line you could say to any request is a failure — use their words."
    )
    user = f"They said: {said}"
    if rejected:
        user += (
            "\n\nThat try was generic and will not be spoken: "
            + rejected.strip()
            + "\nSay a different sentence that could only follow what they said."
        )
    return system, user
