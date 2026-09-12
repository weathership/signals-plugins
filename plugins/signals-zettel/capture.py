"""Write a Gaius-style scratch zettel under the Hermes wiki vault."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SLUG = re.compile(r"[^a-z0-9]+")
_USAGE = "usage: /zettel <pasted text>"


def vault_root(*, env: dict[str, str] | None = None, hermes_home: Path | None = None) -> Path:
    e = os.environ if env is None else env
    for key in ("OBSIDIAN_VAULT_PATH", "WIKI_PATH"):
        raw = str(e.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser()
    if hermes_home is not None:
        return Path(hermes_home) / "wiki"
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "wiki"


def slugify(title: str, *, fallback: str = "note") -> str:
    slug = _SLUG.sub("-", (title or "").strip().lower()).strip("-")[:50]
    return slug or fallback


def zettel_relpath(title: str, *, now: datetime | None = None) -> str:
    clock = now or datetime.now()
    day = clock.strftime("%Y-%m-%d")
    stamp = clock.strftime("%H%M%S")
    return f"scratch/{day}/{stamp}_{slugify(title)}.md"


def title_from_body(body: str) -> str:
    for line in (body or "").splitlines():
        t = line.strip().lstrip("#").strip()
        if t:
            return t[:80]
    return "note"


def capture(
    *,
    body: str = "",
    vault: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create ``scratch/YYYY-MM-DD/HHMMSS_slug.md`` from *body*."""
    text = body or ""
    if not text.strip():
        return {"ok": False, "error": _USAGE}
    heading = title_from_body(text)
    root = Path(vault) if vault is not None else vault_root()
    rel = zettel_relpath(heading, now=now)
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return {"ok": False, "error": f"already exists: {rel}"}
    content = text if text.lstrip().startswith("#") or text.lstrip().startswith("---") else (
        f"# {heading}\n\n{text.rstrip()}\n"
    )
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    resource = f"wiki:{rel}"
    _append_log(root, heading, rel, now=now)
    return {
        "ok": True,
        "path": str(path),
        "relpath": rel,
        "resource": resource,
        "title": heading,
        "bytes": len(content.encode("utf-8")),
    }


def _append_log(root: Path, title: str, rel: str, *, now: datetime | None) -> None:
    log = root / "log.md"
    if not log.is_file():
        return
    clock = now or datetime.now(timezone.utc)
    stamp = clock.strftime("%Y-%m-%d")
    try:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## [{stamp}] zettel | {title}\n- Created: {rel} ({resource_line(rel)})\n")
    except OSError:
        return


def resource_line(rel: str) -> str:
    return f"wiki:{rel}"


def format_slash_result(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        err = str(data.get("error") or "unknown error")
        if err == _USAGE:
            return f"  {_USAGE}"
        return f"  /zettel failed: {err}"
    return (
        f"  Zettel {data['relpath']}\n"
        f"  {data['resource']}\n"
        f"  {data['bytes']} bytes — {data['title']}"
    )


def tool_result(data: dict[str, Any]) -> str:
    payload = dict(data)
    payload["success"] = bool(data.get("ok"))
    return json.dumps(payload, ensure_ascii=False)
