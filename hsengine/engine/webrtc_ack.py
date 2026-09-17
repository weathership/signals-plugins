"""Immediate spoken ack while Ripley works. Combinatorial, not a catchphrase.

Register borrows WarGames (WOPR), Ex Machina, Hackers, Swordfish, and
Sneakers — fragments and cadence, not a five-quote loop. No ticker-tape.
Kyutai TTS only; no Cerebras round.
"""
from __future__ import annotations

import random
import re
import threading

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
    "Hang on",
    "Hold on",
    "Wait one",
    "Just a second",
    "Bear with me",
    "Let me look",
    "Let me pull that",
    "Let me see",
    "I'll take that",
    "Taking that",
    "Working it",
    "Verify me",
    "Play a game",
    "Shall we",
    "Hello Joshua",
    "I want in",
    "Going downtown",
    "Through the glass",
    "No more secrets",
    "Too many secrets",
)

_MIDDLE = (
    "looking",
    "pulling that up",
    "digging",
    "checking",
    "one more look",
    "a second pass",
    "the interesting bit",
    "the real driver",
    "how this sits",
    "how this reads",
    "a cleaner angle",
    "the next useful cut",
    "what to put on glass",
    "whether this still matches",
    "the part that isn't boilerplate",
    "shall we play a game",
    "a strange game",
    "how about chess instead",
    "asking Joshua",
    "waking WOPR",
    "not thermonuclear war",
    "the only winning move",
    "is this a game or is it real",
    "through the glass",
    "BlueBook is quiet",
    "Ava's still behind the glass",
    "it's not the test I wanted",
    "power's still on",
    "hack the planet",
    "mess with the best",
    "no right and wrong, only fun and boring",
    "on the Gibson",
    "Crash Override style",
    "never send a boy",
    "we're elite or we're not",
    "my voice is my passport",
    "too many secrets",
    "no more secrets",
    "checking the box",
    "the good guys for a minute",
    "sixty seconds",
    "building a payload",
    "not a stealth bomber",
    "hydra can wait",
)

_TAIL = (
    "hold on",
    "stay with me",
    "give me a beat",
    "give me a second",
    "don't go anywhere",
    "one moment",
    "almost",
    "on it",
    "coming",
    "hang on",
    "wait one",
    "I've got this",
    "leave it with me",
    "I'll bring it back",
    "won't be long",
    "stay put",
    "keep talking if you want",
    "interrupt me if I'm wrong",
    "this won't take long",
    "then I'll talk",
    "then we can look together",
    "shall we play",
    "verify me",
    "hack the planet",
    "no more secrets",
    "see you downtown",
    "through the glass",
    "payload's cooking",
    "don't start Global Thermonuclear War",
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

# Whole-line nods. Drawn rarely so they stay a spice, not a motif.
_NOD = (
    "Shall we play a game?",
    "How about a nice game of chess?",
    "A strange game.",
    "Would you like to play a game?",
    "Hello, Joshua.",
    "Is this a game or is it real?",
    "The only winning move is not to play. Not this round.",
    "Let's go downtown.",
    "My voice is my passport. Verify me.",
    "Too many secrets.",
    "No more secrets.",
    "Hack the planet.",
    "Mess with the best, die like the rest.",
    "There is no right and wrong. Only fun and boring.",
    "Never send a boy to do a woman's job.",
    "I want in.",
    "We're going in.",
    "Through the glass.",
    "It's a test.",
    "Sixty seconds.",
    "Not an Apache. Not a stealth bomber. Just working.",
)

_HOOK_RE = re.compile(
    r"\b(SLB|HAL|BKR|NOV|NWL|CRM|DOW|MU|8-K|Form\s*4|filings?|chord|"
    r"heatmap|timeline|density|Schlumberger|Halliburton|"
    r"Baker|oilfield|WOPR|Joshua|Gibson)\b",
    re.IGNORECASE,
)

_recent: list[str] = []
_mu = threading.Lock()
_RECENT = 48

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
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    words = text.split()
    if len(words) > 16:
        text = " ".join(words[:16]).rstrip(".,") + "."
    return text


def ack_line(utterance: str = "", *, rng: random.Random | None = None) -> str:
    """One short spoken ack. Combinatorial; avoids the last few lines."""
    rng = rng or random.Random()
    if rng.random() < 0.14:
        nod = rng.choice(_NOD)
        with _mu:
            if nod not in _recent:
                _recent.append(nod)
                del _recent[:-_RECENT]
                return nod
    hook = _hook(utterance)
    middles = list(_MIDDLE)
    if hook:
        middles.extend(
            (
                f"on {hook}",
                f"looking at {hook}",
                f"pulling {hook}",
                f"the {hook} cut",
            )
        )
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
    return len(_OPEN) * len(_MIDDLE) * len(_TAIL) * len(_TEMPLATES) + len(_NOD)
