"""Named Bots for AgentRTC: Ripley (spoken) and Bishop (silent).

A Bot is a Hermes profile under ``~/.hermes/profiles/<name>/`` with Bot-Mode
``ui_meta['hermes-bots']``. Created on first interactive enter if missing.
Both use Cerebras while the AgentRTC Activity is in force (session overlay);
Bishop's profile caps ``delegate_task`` at two concurrent children.
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
    if move == "thought":
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
    return system, "\n".join(lines), 200


def bishop_run(
    *,
    session_id: str,
    idle_s: float = 0.0,
    last_steer: str = "",
    move: str = "deepen",
    glance: str = "",
) -> BishopOutcome:
    """Silent Cerebras turn as Bishop. Never speaks."""
    from hsengine.engine import interactive

    del idle_s  # reserved: phase still chosen by the silence director
    system, prompt, max_tokens = bishop_prompt(
        move=move, glance=glance, last_steer=last_steer
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
