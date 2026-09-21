"""Named Bots for AgentRTC: Ripley (spoken), Bishop (invent), Vasquez (viz).

Agent-mediated: an agent sits between workspace products and the human.
Named agents and sub-agents are that pattern, not a sideline. Bishop
invents; Ripley speaks; Vasquez glances one compositor JPEG at end of
sequence and drives HoloViews. Humans spectate.

A Bot is a Hermes profile under ``~/.hermes/profiles/<name>/`` with Bot-Mode
``ui_meta['hermes-bots']``. Created on first interactive enter if missing.
All three use Cerebras while the AgentRTC Activity is in force (session overlay).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("hsengine.engine.named_bots")

RIPLEY = "ripley"
BISHOP = "bishop"
VASQUEZ = "vasquez"

# Silent invent + tools. Ceiling only; short STEER/MONOLOGUE still stops at EOS.
# Ripley's spoken path stays on webrtc_moshi._ripley_spoken_max_tokens (TTS).
_BISHOP_MAX_TOKENS = 32768
_BISHOP_MIN_TOKENS = 4096

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
_VASQUEZ_META = {
    "display_name": "Vasquez",
    "description": "Silent AgentRTC viz — one compositor JPEG per sequence; drives HoloViews. Never heard.",
    "ui_meta": {
        "hermes-bots": {
            "title": "Vasquez",
            "shape": "blobatar::sharp",
            "color": "#6b8f3c",
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
        if (
            not replace
            and "grok_consult" not in current
            and (
                "You may only call viz_show, viz_select, viz_hover, viz_input, and viz_clear."
                in current
                or "You may call recent_thoughts, kb_search, web_search, or fmp."
                in current
            )
        ):
            replace = True
        managed = (
            "the spoken voice on this AgentRTC call" in current
            or "You are Bishop, the silent session" in current
            or "the silent visual gunner" in current
        )
        if not replace and managed and "kanban_create" in current and "kanban_create" not in template:
            replace = True
        if not replace and managed and "kind=kanban" in template and "kind=kanban" not in current:
            replace = True
        if (
            not replace
            and managed
            and "primary Grok" in template
            and "primary Grok" not in current
        ):
            replace = True
        if not replace and managed and "skill_manage" in template and "skill_manage" not in current:
            replace = True
        if not replace and managed and "cronjob_manage" in template and "cronjob_manage" not in current:
            replace = True
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
        _ensure_one(VASQUEZ, _VASQUEZ_META)
        out[VASQUEZ] = str(_profile_dir(VASQUEZ))
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


def bishop_max_tokens() -> int:
    """Generation ceiling for a silent Bishop invent turn."""
    try:
        from hsengine.config import load_config

        raw = load_config().get("hermes.engine.webrtc.interactive.bishop_max_tokens")
        n = int(raw)
        if n >= _BISHOP_MIN_TOKENS:
            return n
    except Exception:
        pass
    return _BISHOP_MAX_TOKENS


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
            "A greeting is allowed. Prefer MONOLOGUE Ripley can speak now in first "
            "person. STEER is optional color for that line. Do not use a formula "
            "(no casual-hello-plus-two-ideas-then-ask). Do not mention Bishop, "
            "pipelines, or how the notes arrived. Banned rumination frames: "
            "'I've been sitting with', 'turning something over', 'thread I'm "
            "returning to', 'keeps surfacing', 'good to be back'. "
            "Do not grok_consult on Connect. "
            "If the glance has an OWNER SESSION PROMPT, invent from that "
            "prompt — the owning agent wrote it for this Connect. It is not "
            "speaker notes and not recent_thoughts. "
            "If the glance has a CALENDAR SESSION and no owner prompt, they "
            "joined that meeting. That is required opening entropy. Do not "
            "call recent_thoughts. Do not lead with Latest thoughts. One hook "
            "from the session, then the floor. "
            "If the handoff includes a USER-PROVIDED zettel, that is their "
            "paste — not interior monologue, not federated-workspace thoughts, "
            "not Gaius, not recent_thoughts. It is required opening entropy. "
            "Start from one hook in what they wrote, as something they just "
            "put down, then the floor. Do not claim it as ours or as something "
            "Ripley has been sitting with. Do not skip it for a generic "
            "greeting-plus-thought. Do not rundown the whole note. Do not call "
            "recent_thoughts unless the user-zettel block is missing. Older "
            "notes stay quiet. If the workspace glance is stale or empty and "
            "there is no user zettel, have her say the workspace has gone "
            "quiet — do not invent today's news. If the glance has PERSISTENT "
            "FAILURES (Theta miss / not caught up), those are failures: say "
            "so plainly. Do not treat them as briefing. Historical weeks are "
            "daily Airflow increments that refine the week consolidation."
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
        lines.append(
            "Call conversation. Deepen the last live thread. Do not web-search. "
            "If a figure would help (ontology chord, Aegir aperture, a plot), "
            "call viz_show. For multi-track work, skills, or cron automations, "
            "call hermes then viz_show kind=kanban if a board should be on "
            "the video. If the live thread is circling the same complex "
            "idea, grok_consult once then STEER/MONOLOGUE from that."
        )
    lines.append("Then output STEER and MONOLOGUE as specified in your persona.")
    return system, "\n".join(lines), bishop_max_tokens()


def bishop_run(
    *,
    session_id: str,
    idle_s: float = 0.0,
    last_steer: str = "",
    move: str = "deepen",
    glance: str = "",
    handoff: str = "",
    utterance: str = "",
) -> BishopOutcome:
    """Silent Cerebras turn as Bishop. Never speaks."""
    from hsengine.engine import interactive

    try:
        from hsengine.engine.webrtc_activity import pulse

        pulse("bishop")
    except Exception:
        pass
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
            recall_query=(utterance.strip() if utterance.strip() else ""),
        )
    outcome = parse_bishop_reply(getattr(result, "text", "") or "")
    if move != "open":
        return outcome
    from hsengine.engine.opening_tropes import opening_tropes, tropes_retry_line

    hits = opening_tropes(outcome.monologue)
    if not hits:
        return outcome
    retry_prompt = prompt + "\n\n" + tropes_retry_line(hits)
    with bishop_delegation_cap(2):
        retry = interactive.complete_cerebras(
            prompt=retry_prompt,
            system_prompt=system,
            max_tokens=max_tokens,
            temperature=0.7,
            reasoning_effort="none",
            tools=False,
            speak=False,
            session_id=session_id,
            recall_query="",
        )
    retried = parse_bishop_reply(getattr(retry, "text", "") or "")
    if retried.monologue and not opening_tropes(retried.monologue):
        return retried
    if retried.monologue:
        return retried
    return outcome


def ripley_opening_prompts(outcome: BishopOutcome) -> tuple[str, str]:
    """Execute pass: Ripley speaks Bishop's invented opening. No canned stand-in."""
    from hsengine.engine.webrtc_silence import apply_steer_system

    system = apply_steer_system(ripley_spoken_system(), outcome.steer)
    if outcome.monologue:
        from hsengine.engine.opening_tropes import tropes_execute_rail

        user = (
            "The call just connected. Speak this as the first thing they hear, "
            "in your voice — not a briefing, not a formula. "
            + tropes_execute_rail()
            + " If the text contains [pause], that beat is handled for you; "
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
    from hsengine.engine.webrtc_moshi import _ripley_spoken_max_tokens

    ceiling = _ripley_spoken_max_tokens()
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
            max_tokens=ceiling,
            temperature=0.55,
            reasoning_effort="none",
            tools=False,
            speak=True,
            session_id=session_id,
        )
        if getattr(result, "text", ""):
            spoken.append(result.text)
    return " ".join(spoken).strip()


_VASQUEZ_LOCK = threading.Lock()
_VASQUEZ_LAST = 0.0
_VASQUEZ_GAP_S = 2.0


def viz_tool_defs() -> list[dict[str, Any]]:
    from hsengine.engine.ops import CEREBRAS_TOOLS

    names = {
        "viz_show",
        "viz_select",
        "viz_input",
        "viz_clear",
        "viz_hover",
        "grok_consult",
    }
    return [t for t in CEREBRAS_TOOLS if t.get("function", {}).get("name") in names]


def reference_jpeg() -> bytes | None:
    """End-of-sequence compositor frame for instruct (not the spectator video)."""
    import io

    img = None
    try:
        from hsengine.engine.webrtc_viz import _cameras
        from hsengine.engine.webrtc_viz import _session_id as live_sid

        cam = _cameras.get(live_sid())
        if cam is not None:
            img = getattr(cam, "latest_image", None)
    except Exception:
        img = None
    if img is None:
        try:
            from hsengine.engine.webrtc_program import PROGRAM

            img = PROGRAM._image
            if not PROGRAM.active():
                return None
        except Exception:
            return None
    if img is None:
        return None
    try:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=65)
        return buf.getvalue()
    except Exception:
        log.debug("vasquez jpeg encode failed", exc_info=True)
        return None


def vasquez_run(
    *,
    session_id: str,
    reason: str = "",
    narrative: str = "",
    spoken: str = "",
) -> str:
    """One silent instruct glance at the live figure. Never speaks. Never loops."""
    global _VASQUEZ_LAST
    jpeg = reference_jpeg()
    if not jpeg:
        return ""
    now = time.monotonic()
    with _VASQUEZ_LOCK:
        if now - _VASQUEZ_LAST < _VASQUEZ_GAP_S:
            return ""
        _VASQUEZ_LAST = now
    try:
        from hsengine.engine.webrtc_activity import pulse

        pulse("vasquez")
    except Exception:
        pass
    system = load_soul(VASQUEZ)
    lines = [
        f"Reason: {reason or 'end-of-sequence'}.",
        "This is one reference frame of the live HoloViews page after the last beat.",
        "If it already matches, ACTION: NONE.",
        "If the live thread is circling the same complex idea, grok_consult "
        "once then viz; otherwise do not consult.",
    ]
    nar = " ".join((narrative or "").split())
    sp = " ".join((spoken or "").split())
    if nar:
        lines.append("Narrative / user: " + nar[:800])
    if sp:
        lines.append("Ripley just said: " + sp[:800])
    from hsengine.engine import interactive

    result = interactive.complete_cerebras(
        prompt="\n".join(lines),
        system_prompt=system,
        max_tokens=160,
        temperature=0.3,
        reasoning_effort="none",
        tools=True,
        tool_defs=viz_tool_defs(),
        speak=False,
        session_id=session_id,
        recall_query="",
        images=[jpeg],
    )
    text = (getattr(result, "text", "") or "").strip()
    if text:
        log.info("vasquez glance session=%s reason=%s %r", session_id, reason, text[:160])
    return text


def schedule_vasquez_glance(
    *,
    session_id: str,
    reason: str = "",
    narrative: str = "",
    spoken: str = "",
) -> None:
    """Fire-and-forget after a spoken/invent sequence. No poll loop."""
    try:
        from hsengine.engine.webrtc_program import PROGRAM

        if not PROGRAM.active():
            return
    except Exception:
        return

    def _run() -> None:
        try:
            vasquez_run(
                session_id=session_id,
                reason=reason,
                narrative=narrative,
                spoken=spoken,
            )
        except Exception:
            log.exception("vasquez glance failed")

    threading.Thread(target=_run, daemon=True, name="vasquez-glance").start()
