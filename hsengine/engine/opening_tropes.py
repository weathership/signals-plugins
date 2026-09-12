"""Opening rumination frames — the AI tells we keep hearing on Connect.

Not a script. A reject list for Bishop's invent pass and Ripley's execute
pass so "I've been sitting with / thread I'm returning to" cannot ship.
"""
from __future__ import annotations

import re

# Phrase-level, not topics. Content may repeat; these frames may not.
_TROPES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"i['’]?ve been sitting with",
        r"sitting with (something|this|that|a |the )",
        r"worth sitting with",
        r"thread i['’]?ve been",
        r"thread i['’]?m (returning|coming back)",
        r"returning to (this |that |the |a )?(thread|one)",
        r"been turning .{0,40}over",
        r"turning (something|this|that|it) over",
        r"keeps surfacing",
        r"keeps coming (back|up)",
        r"i['’]?ve been circling",
        r"i['’]?ve been thinking about",
        r"something i['’]?ve been",
        r"good to be back",
        r"welcome back",
        r"since we last talked",
        r"pulling at me",
        r"notes sitting around",
        r"threads pulling",
        r"quietly (measuring|telling) (itself|us)",
    )
)

BANNED_FRAMES = (
    "I've been sitting with",
    "sitting with something",
    "thread I've been turning over",
    "thread I'm returning to",
    "turning something over",
    "keeps surfacing",
    "I've been circling",
    "I've been thinking about",
    "good to be back",
    "welcome back",
    "since we last talked",
)


def opening_tropes(text: str) -> list[str]:
    blob = " ".join((text or "").split())
    if not blob:
        return []
    found: list[str] = []
    for pat in _TROPES:
        m = pat.search(blob)
        if m and m.group(0) not in found:
            found.append(m.group(0))
    return found


def tropes_retry_line(hits: list[str]) -> str:
    shown = ", ".join(hits[:6]) if hits else ", ".join(BANNED_FRAMES[:6])
    return (
        "Rewrite the MONOLOGUE. Those rumination frames are banned on Connect: "
        f"{shown}. Say the thing itself, or greet and hand the floor. "
        "No sitting-with, no turning-over, no returning-to-a-thread."
    )


def tropes_execute_rail() -> str:
    return (
        "No rumination frames: not 'sitting with', 'turning over', "
        "'thread I'm returning to', 'keeps surfacing', 'good to be back', "
        "or 'since we last talked'. If the invent draft used those, drop the "
        "frame and speak the observation — or skip it and hand the floor."
    )
