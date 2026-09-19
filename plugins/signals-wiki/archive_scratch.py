"""Move fortnight-old scratch zettels into archive/YYYYQN/MM-DD/.

Rewrites prev/next, about_path, wiki: refs, and [[paths]] across the vault
the way Obsidian rewrites links on a move.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FORTNIGHT_DAYS = 14
_SCRATCH = re.compile(
    r"^scratch/(\d{4})-(\d{2})-(\d{2})/([^/]+\.md)$"
)
CRON_NAME = "wiki-archive-scratch"


def vault_root(*, env: dict[str, str] | None = None) -> Path:
    import os

    e = os.environ if env is None else env
    for key in ("WIKI_PATH", "OBSIDIAN_VAULT_PATH"):
        raw = str(e.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser()
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "wiki"


def quarter_label(year: int, month: int) -> str:
    return f"{year}Q{(month - 1) // 3 + 1}"


def archive_rel(scratch_rel: str) -> str | None:
    match = _SCRATCH.match(scratch_rel.replace("\\", "/"))
    if not match:
        return None
    year, month, day, name = match.groups()
    q = quarter_label(int(year), int(month))
    return f"archive/{q}/{month}-{day}/{name}"


def _day(scratch_rel: str) -> date | None:
    match = _SCRATCH.match(scratch_rel.replace("\\", "/"))
    if not match:
        return None
    year, month, day, _ = match.groups()
    return date(int(year), int(month), int(day))


def due_zettels(root: Path, *, now: date | None = None, days: int = FORTNIGHT_DAYS) -> list[str]:
    today = now or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=days)
    scratch = Path(root) / "scratch"
    if not scratch.is_dir():
        return []
    out: list[str] = []
    for path in sorted(scratch.rglob("*.md")):
        rel = str(path.relative_to(root)).replace("\\", "/")
        day = _day(rel)
        if day is None:
            continue
        if day <= cutoff:
            dest = archive_rel(rel)
            if dest:
                out.append(rel)
    return out


def rewrite_refs(text: str, mapping: dict[str, str]) -> str:
    """Replace old vault-relative paths with new ones (longest first)."""
    if not mapping:
        return text
    updated = text
    for old, new in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
        if old == new:
            continue
        updated = updated.replace(old, new)
    return updated


def _rewrite_vault(root: Path, mapping: dict[str, str]) -> int:
    changed = 0
    for path in Path(root).rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        new = rewrite_refs(text, mapping)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def _empty_parents(path: Path, stop: Path) -> None:
    cur = path.parent
    while cur != stop and cur.is_dir():
        try:
            next(cur.iterdir())
            break
        except StopIteration:
            parent = cur.parent
            cur.rmdir()
            cur = parent


def migrate(
    root: Path | None = None,
    *,
    now: date | None = None,
    days: int = FORTNIGHT_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    vault = Path(root) if root is not None else vault_root()
    due = due_zettels(vault, now=now, days=days)
    mapping: dict[str, str] = {}
    skipped: list[str] = []
    for rel in due:
        dest = archive_rel(rel)
        if not dest:
            continue
        if (vault / dest).exists():
            skipped.append(rel)
            continue
        mapping[rel] = dest
    refs = dict(mapping)
    for old, new in mapping.items():
        if old.endswith(".md"):
            refs.setdefault(old[:-3], new[:-3])
    moved: list[dict[str, str]] = []
    if not dry_run:
        for old, new in mapping.items():
            src = vault / old
            dst = vault / new
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
            moved.append({"from": old, "to": new})
            _empty_parents(src, vault / "scratch")
        rewritten = _rewrite_vault(vault, refs) if refs else 0
        if mapping:
            _append_log(vault, moved)
    else:
        rewritten = 0
        moved = [{"from": o, "to": n} for o, n in mapping.items()]
    return {
        "ok": True,
        "dry_run": dry_run,
        "days": days,
        "moved": moved,
        "skipped": skipped,
        "rewritten_files": rewritten,
    }


def _append_log(root: Path, moved: list[dict[str, str]]) -> None:
    log = Path(root) / "log.md"
    if not log.is_file() or not moved:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n## [{stamp}] archive | scratch zettels\n"]
    for item in moved:
        lines.append(f"- {item['from']} → {item['to']}\n")
    try:
        with log.open("a", encoding="utf-8") as fh:
            fh.writelines(lines)
    except OSError:
        return


def ensure_cron_job() -> dict[str, Any]:
    from cron.jobs import create_job, list_jobs

    for job in list_jobs(include_disabled=True):
        if job.get("name") == CRON_NAME:
            return {"ok": True, "id": job.get("id"), "existing": True}
    script = f"{sys.executable} {Path(__file__).resolve()}"
    job = create_job(
        prompt=None,
        schedule="every 1d",
        name=CRON_NAME,
        script=script,
        no_agent=True,
        deliver="local",
    )
    return {"ok": True, "id": job.get("id"), "existing": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive scratch zettels older than a fortnight."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=FORTNIGHT_DAYS)
    parser.add_argument("--install-cron", action="store_true")
    args = parser.parse_args(argv)
    if args.install_cron:
        print(json.dumps(ensure_cron_job()))
        return 0
    result = migrate(days=args.days, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
