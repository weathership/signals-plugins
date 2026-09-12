"""AgentRTC opening plan: gestures → sequence → Bishop handoff.

Synth vocabulary: a gesture is atomic; a sequence is ordered gestures with
pacing; the objective is a first turn that uses what is actually available.
The catalog is textproto (``opening_gestures.textproto``) so it can iterate
without a Python lock-in.
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from google.protobuf import text_format

from hsengine.engine.generated import opening_pb2

log = logging.getLogger("hsengine.engine.opening")

_CATALOG_PATH = Path(__file__).with_name("opening_gestures.textproto")
_LEDGER_NAME = "opening-sequences.jsonl"
_LEDGER_KEEP = 16
RETURNING_HOURS = 36.0

Rng = Callable[[], float]


@dataclass(frozen=True)
class Listener:
    timezone: str = ""
    hour: int = 0
    tod: str = ""
    weekday: str = ""


@dataclass
class OpeningPlan:
    sequence: list[str] = field(default_factory=list)
    facts: frozenset[str] = field(default_factory=frozenset)
    listener: Listener = field(default_factory=Listener)
    handoff: str = ""


def load_catalog(path: Path | None = None) -> opening_pb2.Catalog:
    src = path or _CATALOG_PATH
    cat = opening_pb2.Catalog()
    text_format.Parse(src.read_text(encoding="utf-8"), cat)
    if not cat.sequence.min_gestures:
        cat.sequence.min_gestures = 1
    if not cat.sequence.max_gestures:
        cat.sequence.max_gestures = 3
    return cat


def local_clock(tz_name: str, *, now: datetime | None = None) -> Listener:
    name = (tz_name or "").strip() or "UTC"
    try:
        tz = ZoneInfo(name)
    except Exception:
        tz = dt_timezone.utc
        name = "UTC"
    stamp = now or datetime.now(tz)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=tz)
    else:
        stamp = stamp.astimezone(tz)
    hour = stamp.hour
    if 5 <= hour < 12:
        tod = "morning"
    elif 12 <= hour < 17:
        tod = "afternoon"
    elif 17 <= hour < 22:
        tod = "evening"
    else:
        tod = "night"
    return Listener(timezone=name, hour=hour, tod=tod, weekday=stamp.strftime("%A"))


def facts_from_pack(pack: dict[str, str] | None, *, returning: bool) -> frozenset[str]:
    pack = pack or {}
    workspace = (pack.get("workspace") or "").strip()
    tags: set[str] = {"always"}
    if returning:
        tags.add("returning")
    if usable(pack.get("thoughts_spoken")):
        tags.add("has_thoughts")
    if usable(pack.get("agenda_spoken")):
        tags.add("has_agenda")
    if workspace == "fresh":
        tags.add("has_fresh")
    elif workspace == "stale":
        tags.add("stale")
    elif workspace == "empty":
        tags.add("empty")
    return frozenset(tags)


def usable(text: str | None) -> bool:
    return bool((text or "").strip()) and len((text or "").strip()) >= 24


def _eligible(g: opening_pb2.Gesture, facts: frozenset[str]) -> bool:
    if g.id == "pause" or g.weight <= 0:
        return False
    needed = [t for t in g.when if t and t != "always"]
    return all(t in facts for t in needed)


def _recent_ids(ledger: Path, n: int = 3) -> list[list[str]]:
    if not ledger.is_file():
        return []
    try:
        lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []
    out: list[list[str]] = []
    for ln in lines[-n:]:
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        seq = [s for s in (row.get("sequence") or []) if s and s != "pause"]
        if seq:
            out.append(seq)
    return out


def _anti_repeat(weight: float, gid: str, recent: list[list[str]]) -> float:
    if not recent:
        return weight
    if recent[-1] and gid in recent[-1]:
        return weight * 0.22
    if any(gid in seq for seq in recent):
        return weight * 0.55
    return weight


def _pick(weighted: list[tuple[str, float]], rng: Rng) -> str | None:
    total = sum(max(0.0, w) for _, w in weighted)
    if total <= 0:
        return None
    cursor = rng() * total
    acc = 0.0
    for gid, w in weighted:
        acc += max(0.0, w)
        if cursor <= acc:
            return gid
    return weighted[-1][0]


def _insert_pause(content: list[str], policy: opening_pb2.SequencePolicy, rng: Rng) -> list[str]:
    if not content:
        return content
    rolls = sorted(((p.after, p.p) for p in policy.pause_after if p.after >= 1), key=lambda x: x[0])
    chosen: int | None = None
    for after, p in rolls:
        if after <= len(content) and rng() < p:
            chosen = after
            break
    if chosen is None:
        return content
    out = list(content)
    out.insert(chosen, "pause")
    return out


def _ledger_path() -> Path:
    try:
        from hsengine.engine.moshi_supervisor import devenv_root

        return devenv_root() / ".devenv" / "state" / _LEDGER_NAME
    except Exception:
        return Path.cwd() / ".devenv" / "state" / _LEDGER_NAME


def remember_sequence(sequence: list[str], *, session_id: str = "") -> None:
    path = _ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"sequence": sequence, "session_id": session_id}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _LEDGER_KEEP:
            path.write_text("\n".join(lines[-_LEDGER_KEEP:]) + "\n", encoding="utf-8")
    except OSError:
        log.debug("opening ledger write failed", exc_info=True)


def sample_sequence(
    catalog: opening_pb2.Catalog,
    facts: frozenset[str],
    *,
    rng: Rng | None = None,
    recent: list[list[str]] | None = None,
) -> list[str]:
    rng = rng or random.random
    recent = recent if recent is not None else _recent_ids(_ledger_path())
    weights: dict[str, float] = {}
    for g in catalog.gesture:
        if not _eligible(g, facts):
            continue
        w = _anti_repeat(float(g.weight), g.id, recent)
        if g.id == "headline" and "has_fresh" in facts and "has_thoughts" in facts:
            w *= 1.35  # notable thread jumps the queue
        if g.id == "rundown" and "has_fresh" in facts:
            w *= 0.4
        weights[g.id] = max(weights.get(g.id, 0.0), w)
    pool = [(gid, w) for gid, w in weights.items() if w > 0]
    lo = max(1, int(catalog.sequence.min_gestures) or 1)
    hi = max(lo, int(catalog.sequence.max_gestures) or 3)
    hi = min(hi, max(1, len(pool)))
    span = hi - lo + 1
    n = lo + (min(span - 1, int(rng() * span)) if span > 1 else 0)
    picked: list[str] = []
    remaining = list(pool)
    for _ in range(n):
        choice = _pick(remaining, rng)
        if not choice:
            break
        picked.append(choice)
        remaining = [(i, w) for i, w in remaining if i != choice]
    if not picked and pool:
        picked = [pool[0][0]]
    return _insert_pause(picked, catalog.sequence, rng)


def _instruction(catalog: opening_pb2.Catalog, gid: str, facts: frozenset[str]) -> str:
    matches = [g for g in catalog.gesture if g.id == gid]
    if not matches:
        return gid
    for g in matches:
        if _eligible(g, facts) or gid == "pause":
            return g.instruction
    return matches[0].instruction


def bishop_handoff(
    plan_seq: list[str],
    *,
    listener: Listener,
    facts: frozenset[str],
    glance: str = "",
    catalog: opening_pb2.Catalog | None = None,
) -> str:
    cat = catalog or load_catalog()
    lines = [
        f"Listener: timezone={listener.timezone} local={listener.hour:02d}:00 "
        f"tod={listener.tod} weekday={listener.weekday} "
        f"returning={'yes' if 'returning' in facts else 'no'}.",
        "Opening sequence (synth: gesture → sequence; pause is a beat): "
        + " → ".join(plan_seq or ["offer_floor"]),
    ]
    for gid in plan_seq:
        lines.append(f"- {gid}: {_instruction(cat, gid, facts)}")
    if glance.strip():
        lines.append("Workspace glance:\n" + glance.strip())
    lines.append(
        "Invent MONOLOGUE Ripley speaks, honoring this sequence. "
        "Mark a sequence pause as [pause] in the MONOLOGUE. "
        "Do not name the gestures. Do not mention Bishop."
    )
    return "\n".join(lines)


def compose_opening(
    *,
    pack: dict[str, str] | None = None,
    timezone: str = "",
    session_id: str = "",
    returning: bool | None = None,
    rng: Rng | None = None,
    catalog: opening_pb2.Catalog | None = None,
) -> OpeningPlan:
    cat = catalog or load_catalog()
    listener = local_clock(timezone)
    if returning is None:
        returning = bool(_returning(exclude=session_id))
    facts = facts_from_pack(pack, returning=returning)
    seq = sample_sequence(cat, facts, rng=rng)
    from hsengine.engine.context_pack import pipeline_block

    glance = pipeline_block(pack)
    handoff = bishop_handoff(seq, listener=listener, facts=facts, glance=glance, catalog=cat)
    remember_sequence(seq, session_id=session_id)
    log.info("opening sequence=%s facts=%s tz=%s tod=%s", seq, sorted(facts), listener.timezone, listener.tod)
    return OpeningPlan(sequence=seq, facts=facts, listener=listener, handoff=handoff)


def _returning(*, exclude: str = "") -> bool:
    hours = last_connect_age_hours(exclude=exclude)
    return hours is not None and 0.0 <= hours <= RETURNING_HOURS


def last_connect_age_hours(*, exclude: str = "") -> float | None:
    try:
        from hsengine.engine import session_history as sh

        db = sh._store()
        if db is None or not hasattr(db, "list_sessions_rich"):
            return None
        rows = db.list_sessions_rich(
            source=sh.SOURCE, limit=12, order_by_last_active=True, compact_rows=True
        )
    except Exception:
        return None
    skip = sh.hermes_session_id(exclude) if exclude else ""
    import time as _time

    now = _time.time()
    for row in rows or []:
        sid = str(row.get("id") or "")
        if skip and sid == skip:
            continue
        raw = row.get("ended_at") or row.get("last_active") or row.get("started_at")
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            continue
        if ts > 1e12:
            ts = ts / 1000.0
        if ts <= 0:
            continue
        return max(0.0, (now - ts) / 3600.0)
    return None


_PAUSE = re.compile(r"\s*\[pause\]\s*", re.I)


def split_spoken_beats(text: str) -> list[str]:
    parts = _PAUSE.split(text or "")
    return [p.strip() for p in parts if p.strip()]
