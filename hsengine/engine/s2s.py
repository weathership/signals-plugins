"""Server-to-server query helpers (signals-protocol Engine/ServerQuery).

Matrix S2S Queries: pairwise snapshot. Not epidemic gossip. Honest empty for
kinds we do not serve yet.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from hsengine.engine import federation, surfaces
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

log = logging.getLogger("hsengine.engine.s2s")

PROJECT = "hermes"

_RUNNING_SHA: str = ""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def stamp_running_sha(root: Path | None = None) -> str:
    global _RUNNING_SHA
    _RUNNING_SHA = advertised_head(root)
    return _RUNNING_SHA


def advertised_head(root: Path | None = None) -> str:
    checkout = root or repo_root()
    try:
        proc = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def list_named_remotes(root: Path | None = None) -> list[tuple[str, str]]:
    checkout = root or repo_root()
    proc_out = _git(checkout, "remote", "-v")
    seen: dict[str, str] = {}
    for line in proc_out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        if "(push)" in line and name in seen:
            continue
        if name not in seen:
            seen[name] = url
    return [(name, seen[name]) for name in seen]


def current_branch(root: Path | None = None) -> str:
    text = _git(root or repo_root(), "rev-parse", "--abbrev-ref", "HEAD")
    return "" if text == "HEAD" else text


def working_tree_dirty(root: Path | None = None) -> bool:
    return bool(_git(root or repo_root(), "status", "--porcelain"))


def upstream_ahead_behind(root: Path | None = None) -> tuple[str, int, int]:
    checkout = root or repo_root()
    upstream = _git(checkout, "rev-parse", "--abbrev-ref", "@{upstream}")
    if not upstream:
        return "", 0, 0
    counts = _git(checkout, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
    if not counts:
        return upstream, 0, 0
    parts = counts.split()
    if len(parts) != 2:
        return upstream, 0, 0
    behind, ahead = int(parts[0]), int(parts[1])
    return upstream, ahead, behind


def build_source_posture(root: Path | None = None, *, project: str = PROJECT) -> zpb.SourcePosture:
    checkout = Path(root or repo_root())
    up, ahead, behind = upstream_ahead_behind(checkout)
    return zpb.SourcePosture(
        project=project,
        checkout=str(checkout),
        branch=current_branch(checkout),
        head=advertised_head(checkout),
        running_sha=_RUNNING_SHA or advertised_head(checkout),
        dirty=working_tree_dirty(checkout),
        upstream=up,
        ahead=ahead,
        behind=behind,
    )


def local_response(kind: int, *, dashboard_healthy: bool = True) -> zpb.ServerQueryResponse:
    resp = zpb.ServerQueryResponse(project=PROJECT)
    if kind in (
        zpb.SERVER_QUERY_KIND_UNSPECIFIED,
        zpb.SERVER_QUERY_KIND_REMOTES,
    ):
        remotes = list_named_remotes()
        resp.remotes.extend(zpb.GitRemote(name=name, url=url) for name, url in remotes)
        resp.head = advertised_head()
    if kind == zpb.SERVER_QUERY_KIND_PEERS:
        for project, target in federation.peer_hints():
            resp.peers.append(
                zpb.PeerHint(project=project, target=surfaces.canonical_target(target))
            )
    if kind == zpb.SERVER_QUERY_KIND_SURFACES:
        resp.surfaces.extend(surfaces.local_surfaces(dashboard_healthy))
    if kind == zpb.SERVER_QUERY_KIND_SOURCE_POSTURE:
        resp.posture.CopyFrom(build_source_posture(project=PROJECT))
    if kind == zpb.SERVER_QUERY_KIND_ACTIVITIES:
        # Coordination Activities this engine knows (its own + peers', learned
        # from Signals). Local processes read them HERE, never from Signals.
        from hsengine.engine import coordination

        resp.activities.extend(coordination.activities_proto())
    if kind == zpb.SERVER_QUERY_KIND_AGENTS:
        from hsengine.engine import agents

        resp.agents.append(agents.hint())
    if kind == zpb.SERVER_QUERY_KIND_SCHEDULES:
        # This engine's WORKLOAD CATALOGUE — the same entries it submits to
        # Signals (Scheduler/SyncWorkloads): the interactive agent-rtc workflow,
        # source=engine (declared at session start, not scheduled).
        from hsengine.engine import workload_catalog

        resp.schedules.extend(workload_catalog.catalog())
    return resp
