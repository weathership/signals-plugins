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


_ABOUT_PATH = re.compile(r"(?m)^about_path:\s*(.+?)\s*$")
_NEXT_LINE = re.compile(r"(?m)^next:\s*.*$")


def _slug_of_about(about: str) -> str:
    text = (about or "").strip().replace("\\", "/")
    text = text.replace("[[", "").replace("]]", "").strip()
    if text.endswith(".md"):
        text = text[:-3]
    return Path(text).name.lower()


def latest_zettel_about(root: Path, about: str) -> str | None:
    """Newest scratch zettel that discusses *about* (path or [[slug]])."""
    slug = _slug_of_about(about)
    if not slug:
        return None
    scratch = Path(root) / "scratch"
    if not scratch.is_dir():
        return None
    hits: list[tuple[float, str]] = []
    for path in scratch.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        about_path = ""
        m = _ABOUT_PATH.search(text)
        if m:
            about_path = m.group(1).strip().strip("\"'")
        if _slug_of_about(about_path) == slug:
            hits.append((path.stat().st_mtime, rel))
            continue
        if re.search(
            rf"(?m)^about:\s*\[\[{re.escape(slug)}\]\]",
            text,
            re.IGNORECASE,
        ):
            hits.append((path.stat().st_mtime, rel))
    if not hits:
        return None
    hits.sort()
    return hits[-1][1]


def _set_next(root: Path, rel: str, nxt: str) -> None:
    path = Path(root) / rel
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if _NEXT_LINE.search(text):
        text = _NEXT_LINE.sub(f"next: {nxt}", text, count=1)
    elif text.startswith("---"):
        text = text.replace("---\n", f"---\nnext: {nxt}\n", 1)
    else:
        return
    path.write_text(text, encoding="utf-8")


def capture(
    *,
    body: str = "",
    vault: Path | None = None,
    now: datetime | None = None,
    about: str = "",
) -> dict[str, Any]:
    """Create ``scratch/YYYY-MM-DD/HHMMSS_slug.md`` from *body*.

    When *about* names a long-running ``current/`` doc, ``prev`` is the last
    scratch zettel that discussed it and that file's ``next`` is updated.
    """
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
    about = (about or "").strip()
    prev = latest_zettel_about(root, about) if about else ""
    about_path = about
    if about and not about.endswith(".md") and "[[" not in about:
        if not about.startswith("current/"):
            about_path = about
    body_core = text if text.lstrip().startswith("#") or text.lstrip().startswith("---") else (
        f"# {heading}\n\n{text.rstrip()}\n"
    )
    if body_core.lstrip().startswith("---"):
        content = body_core
    else:
        slug = _slug_of_about(about) if about else ""
        fm = [
            "---",
            f"title: {heading}",
            f"created: {(now or datetime.now()).strftime('%Y-%m-%d')}",
            "type: zettel",
            f"about: [[{slug}]]" if slug else "about: \"\"",
            f"about_path: {about_path}" if about_path else "about_path: \"\"",
            f"prev: {prev}" if prev else "prev: \"\"",
            "next: \"\"",
            "---",
            "",
        ]
        content = "\n".join(fm) + body_core.lstrip()
        if about and f"[[{slug}]]" not in content:
            content = content.rstrip() + f"\n\nAbout: [[{slug}]]\n"
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    if prev:
        _set_next(root, prev, rel)
    resource = f"wiki:{rel}"
    _append_log(root, heading, rel, now=now)
    return {
        "ok": True,
        "path": str(path),
        "relpath": rel,
        "resource": resource,
        "title": heading,
        "bytes": len(content.encode("utf-8")),
        "prev": prev or "",
        "about": about,
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
