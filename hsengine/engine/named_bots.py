"""Named Bots for AgentRTC: Ripley (spoken) and Bishop (silent).

Agent-mediated: an agent sits between workspace products and the human.
Named agents and sub-agents are that pattern, not a sideline. Bishop
invents (tools, up to two ``delegate_task`` children). Ripley speaks.
Connect and later quiet both use that invent-then-execute pass.

A Bot is a Hermes profile under ``~/.hermes/profiles/<name>/`` with Bot-Mode
``ui_meta['hermes-bots']``. Created on first interactive enter if missing.
Both use Cerebras while the AgentRTC Activity is in force (session overlay).
"""
from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("hsengine.engine.named_bots")

RIPLEY = "ripley"
BISHOP = "bishop"

_BOTS_ROOT = Path(__file__).resolve().parent.parent / "bots"

_RIPLEY_META = {
    "display_name": "Ripley",
    "description": "Spoken AgentRTC voice — dialog and thoughts-based contemplation.",
    "ui_meta": {
        "hermes-bots": {
            "title": "Ripley",
            "shape": "blobatar::organic",
            "color": "#c45c26",
        }
    },
}
_BISHOP_META = {
    "display_name": "Bishop",
    "description": "Silent AgentRTC session — steers Ripley's narrative; up to two delegate_task children.",
    "ui_meta": {
        "hermes-bots": {
            "title": "Bishop",
            "shape": "blobatar::boxy",
            "color": "#c8d4e0",
        }
    },
}

_STEER_LINE = re.compile(r"(?im)^\s*STEER:\s*(.*)$")
_MONO_LINE = re.compile(r"(?im)^\s*MONOLOGUE:\s*(.*)$")
_NONE = frozenset({"", "none", "n/a", "-"})


@dataclass(frozen=True)
class BishopOutcome:
    steer: str = ""
    monologue: str = ""


def template_soul(name: str) -> str:
    path = _BOTS_ROOT / name / "SOUL.md"
    return path.read_text(encoding="utf-8").strip()


def _profile_dir(name: str) -> Path:
    from hermes_cli.profiles import get_profile_dir

    return get_profile_dir(name)


def _merge_profile_yaml(profile_dir: Path, *, display_name: str, description: str, ui_meta: dict) -> None:
    from hermes_cli.profiles import write_profile_meta
    from utils import atomic_yaml_write

    write_profile_meta(
        profile_dir, description=description, description_auto=False, display_name=display_name
    )
    path = profile_dir / "profile.yaml"
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            import yaml

            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            log.warning("could not parse %s", path, exc_info=True)
    current = existing.get("ui_meta") if isinstance(existing.get("ui_meta"), dict) else {}
    bots = current.get("hermes-bots") if isinstance(current.get("hermes-bots"), dict) else {}
    incoming = ui_meta.get("hermes-bots") if isinstance(ui_meta.get("hermes-bots"), dict) else {}
    current["hermes-bots"] = {**bots, **incoming}
    existing["ui_meta"] = current
    atomic_yaml_write(path, existing, sort_keys=False)


def _seed_bishop_config(profile_dir: Path) -> None:
    path = profile_dir / "config.yaml"
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            import yaml

            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            return
    delegation = existing.get("delegation") if isinstance(existing.get("delegation"), dict) else {}
    if delegation.get("max_concurrent_children") is not None:
        return
    existing["delegation"] = {
        **delegation,
        "max_concurrent_children": 2,
        "max_spawn_depth": 1,
    }
    from utils import atomic_yaml_write

    atomic_yaml_write(path, existing, sort_keys=False)


def _ensure_one(name: str, meta: dict[str, Any]) -> Path:
    from hermes_cli.profiles import create_profile, profile_exists

    if not profile_exists(name):
        create_profile(
            name=name,
            no_skills=True,
            no_alias=True,
            description=str(meta["description"]),
        )
        log.info("created named bot profile %s", name)
    dest = _profile_dir(name)
    soul = dest / "SOUL.md"
    template = template_soul(name)
    current = soul.read_text(encoding="utf-8").strip() if soul.is_file() else ""
    replace = not current
    if current:
        try:
            from hermes_cli.default_soul import (
                DEFAULT_SOUL_MD,
                _normalize_soul,
                is_legacy_template_soul,
            )

            replace = is_legacy_template_soul(current) or (
                _normalize_soul(current) == _normalize_soul(DEFAULT_SOUL_MD)
            )
        except Exception:
            replace = False
    if replace:
        soul.write_text(template + "\n", encoding="utf-8")
    _merge_profile_yaml(
        dest,
        display_name=str(meta["display_name"]),
        description=str(meta["description"]),
        ui_meta=dict(meta["ui_meta"]),
    )
    if name == BISHOP:
        _seed_bishop_config(dest)
    return dest


def ensure_bots() -> dict[str, str]:
    """Create Ripley and Bishop profiles if missing. Best-effort; never raises."""
    out: dict[str, str] = {}
    try:
        _ensure_one(RIPLEY, _RIPLEY_META)
        out[RIPLEY] = str(_profile_dir(RIPLEY))
        _ensure_one(BISHOP, _BISHOP_META)
        out[BISHOP] = str(_profile_dir(BISHOP))
    except Exception:
        log.warning("ensure AgentRTC named bots failed", exc_info=True)
    return out


def load_soul(name: str) -> str:
    try:
        path = _profile_dir(name) / "SOUL.md"
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        log.debug("load_soul %s failed", name, exc_info=True)
    try:
        return template_soul(name)
    except OSError:
        return ""


def ripley_spoken_system() -> str:
    from hsengine.engine.webrtc_moshi import SPOKEN_SYSTEM

    soul = load_soul(RIPLEY)
    if not soul:
        return SPOKEN_SYSTEM
    return soul + "\n\n" + SPOKEN_SYSTEM


def parse_bishop_reply(text: str) -> BishopOutcome:
    raw = (text or "").strip()
    if not raw:
        return BishopOutcome()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return BishopOutcome(
                steer=_clean_field(data.get("steer")),
                monologue=_clean_field(data.get("monologue")),
            )
    steer_m = _STEER_LINE.search(raw)
    mono_m = _MONO_LINE.search(raw)
    if steer_m or mono_m:
        return BishopOutcome(
            steer=_clean_field(steer_m.group(1) if steer_m else ""),
            monologue=_clean_field(mono_m.group(1) if mono_m else ""),
        )
    from hsengine.engine.webrtc_silence import strip_steer

    return BishopOutcome(steer=strip_steer(raw))


def _clean_field(value: Any) -> str:
    from hsengine.engine.webrtc_silence import strip_steer

    text = strip_steer(str(value or ""))
    if text.lower() in _NONE:
        return ""
    return text


@contextmanager
def bishop_delegation_cap(n: int = 2) -> Iterator[None]:
    """Cap concurrent delegate_task children for the Bishop turn."""
    import tools.delegate_tool_config as dtc

    orig = dtc._get_max_concurrent_children
    dtc._get_max_concurrent_children = lambda: max(1, int(n))
    try:
        yield
    finally:
        dtc._get_max_concurrent_children = orig


def bishop_prompt(
    *,
    move: str = "deepen",
    glance: str = "",
    last_steer: str = "",
    handoff: str = "",
) -> tuple[str, str, int]:
    """system, user prompt, max_tokens for a silent Bishop turn."""
    system = load_soul(BISHOP)
    lines = [f"Move this turn: {move}."]
    last = " ".join((last_steer or "").split())
    if last:
        lines.append("Previous steer (do not repeat): " + last)
    glance_txt = " ".join((glance or "").split())
    if glance_txt:
        lines.append("Cognition glance:\n" + glance_txt)
    handoff_txt = (handoff or "").strip()
    if handoff_txt:
        lines.append("Handoff (opening sequence):\n" + handoff_txt)
    if move == "next":
        lines.append(
            "They asked what's next, the agenda, or how things are. Invent "
            "Ripley's spoken reply from the handoff sequence. Collaborator, "
            "not scheduler. Not a briefing. Not a peer list or operating-posture "
            "readout. Prefer MONOLOGUE. Mark sequence pauses as [pause]. "
            "You may call agenda, sitrep, or recent_thoughts to inform the "
            "invent pass — Ripley will not read those payloads aloud."
        )
    elif move == "open":
        lines.append(
            "This is Connect — invent the first thing they will hear, not a pause. "
            "A greeting is allowed. Call recent_thoughts; kb_search, web_search, or "
            "hermes (delegate_task, at most two children) only if it earns a place. "
            "Prefer MONOLOGUE Ripley can speak now in first person. STEER is optional "
            "color for that line. Do not use a formula "
            "(no casual-hello-plus-two-ideas-then-ask). Do not mention Bishop, "
            "pipelines, or how the notes arrived. If the workspace glance is stale "
            "or empty, have her say the workspace has gone quiet — do not invent "
            "today's news."
        )
    elif move == "thought":
        lines.append("Call conversation, then recent_thoughts.")
    elif move == "kb":
        lines.append("Call conversation, then kb_search once on something from the thread.")
    elif move == "world":
        if glance_txt:
            lines.append(
                "Call conversation. Use the glance if it sits next to the live "
                "thread; otherwise deepen. Do not web-search unless the glance is empty."
            )
        else:
            lines.append(
                "Call conversation, then web_search or fmp once for one adjacent spark."
            )
    else:
        lines.append("Call conversation. Deepen the last live thread. Do not web-search.")
    lines.append("Then output STEER and MONOLOGUE as specified in your persona.")
    return system, "\n".join(lines), 240 if move in ("open", "next") else 200


def bishop_run(
    *,
    session_id: str,
    idle_s: float = 0.0,
    last_steer: str = "",
    move: str = "deepen",
    glance: str = "",
    handoff: str = "",
) -> BishopOutcome:
    """Silent Cerebras turn as Bishop. Never speaks."""
    from hsengine.engine import interactive

    del idle_s  # reserved: phase still chosen by the silence director
    system, prompt, max_tokens = bishop_prompt(
        move=move, glance=glance, last_steer=last_steer, handoff=handoff
    )
    with bishop_delegation_cap(2):
        result = interactive.complete_cerebras(
            prompt=prompt,
            system_prompt=system,
            max_tokens=max_tokens,
            temperature=0.7,
            reasoning_effort="none",
            tools=True,
            speak=False,
            session_id=session_id,
        )
    return parse_bishop_reply(getattr(result, "text", "") or "")


def ripley_opening_prompts(outcome: BishopOutcome) -> tuple[str, str]:
    """Execute pass: Ripley speaks Bishop's invented opening. No canned stand-in."""
    from hsengine.engine.webrtc_silence import apply_steer_system

    system = apply_steer_system(ripley_spoken_system(), outcome.steer)
    if outcome.monologue:
        user = (
            "The call just connected. Speak this as the first thing they hear, "
            "in your voice — not a briefing, not a formula. "
            "If the text contains [pause], that beat is handled for you; "
            "do not say the word pause:\n"
            + outcome.monologue
        )
    elif outcome.steer:
        user = (
            "The call just connected. Speak first. Natural, specific, unhurried. "
            "Do not use a two-ideas-then-ask formula. Do not name Bishop."
        )
    else:
        raise RuntimeError("bishop opening returned empty; no fallback")
    return system, user


async def ripley_speak_outcome(
    outcome: BishopOutcome,
    *,
    session_id: str,
    speech: Any | None = None,
) -> str:
    """Execute pass: Ripley speaks Bishop's invent, honoring [pause] beats."""
    import asyncio

    from hsengine.engine import interactive
    from hsengine.engine.opening import split_spoken_beats

    beats = split_spoken_beats(outcome.monologue) if outcome.monologue else [""]
    spoken: list[str] = []
    for i, beat in enumerate(beats):
        if i:
            await asyncio.sleep(0.55)
            for _ in range(36):
                speaking = getattr(speech, "speaking", None)
                if not callable(speaking) or not speaking():
                    break
                await asyncio.sleep(0.12)
            await asyncio.sleep(0.4)
        chunk = BishopOutcome(
            steer=outcome.steer if i == 0 else "",
            monologue=beat,
        )
        speak_s, speak_u = ripley_opening_prompts(chunk)
        result = await asyncio.to_thread(
            interactive.complete_cerebras,
            prompt=speak_u,
            system_prompt=speak_s,
            max_tokens=220 if i else 280,
            temperature=0.55,
            reasoning_effort="none",
            tools=False,
            speak=True,
            session_id=session_id,
        )
        if getattr(result, "text", ""):
            spoken.append(result.text)
    return " ".join(spoken).strip()
