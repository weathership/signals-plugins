"""signals-wiki dashboard API at /api/plugins/signals-wiki/.

Vault on disk is the AgentRTC write target. Objects are also stored on
Signals rustfs under bucket ``hermes``, prefix ``wiki/`` so the notes
sit with other Signals content.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("signals_wiki")

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")

router = APIRouter()

BUCKET = os.environ.get("HERMES_WIKI_S3_BUCKET", "hermes")
PREFIX = os.environ.get("HERMES_WIKI_S3_PREFIX", "wiki").strip("/")
RUSTFS_URL = os.environ.get("SIGNALS_RUSTFS_URL", "http://127.0.0.1:9010")


def vault_path() -> Path:
    raw = (os.environ.get("WIKI_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / "wiki"
    except Exception:
        return Path.home() / ".hermes" / "wiki"


def _safe(rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or rel.endswith("/"):
        raise HTTPException(status_code=400, detail="path required")
    parts = Path(rel).parts
    if any(p in ("..", "") for p in parts):
        raise HTTPException(status_code=400, detail="bad path")
    vault = vault_path().resolve()
    full = (vault / rel).resolve()
    if not full.is_relative_to(vault):
        raise HTTPException(status_code=400, detail="outside vault")
    return full


def _s3():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=RUSTFS_URL,
        aws_access_key_id=os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin"),
        aws_secret_access_key=os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin"),
        config=Config(s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def ensure_bucket() -> bool:
    try:
        client = _s3()
        buckets = {b["Name"] for b in client.list_buckets().get("Buckets") or []}
        if BUCKET not in buckets:
            client.create_bucket(Bucket=BUCKET)
            log.info("created rustfs bucket %s at %s", BUCKET, RUSTFS_URL)
        return True
    except Exception:
        log.debug("wiki rustfs bucket skipped", exc_info=True)
        return False


def _object_key(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    return f"{PREFIX}/{rel}" if PREFIX else rel


def _mirror_put(rel: str, body: bytes) -> None:
    try:
        if not ensure_bucket():
            return
        _s3().put_object(
            Bucket=BUCKET,
            Key=_object_key(rel),
            Body=body,
            ContentType="text/markdown; charset=utf-8",
        )
    except Exception:
        log.debug("wiki rustfs put skipped", exc_info=True)


def extract_wikilinks(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _WIKILINK.finditer(text or ""):
        target = (match.group(1) or "").strip()
        label = (match.group(2) or target).strip()
        if not target or target in seen:
            continue
        seen.add(target)
        out.append({"target": target, "label": label})
    return out


def resolve_wikilink(pages: list[dict], query: str) -> str | None:
    """Map [[target]] onto a vault-relative .md path. Unique stem wins."""
    q = (query or "").replace("\\", "/").strip().lstrip("/")
    if not q:
        return None
    if q.endswith(".md"):
        q = q[:-3]
    paths = [str(p.get("path") or "") for p in pages]
    exact = f"{q}.md"
    if exact in paths:
        return exact
    stem = Path(q).name.lower()
    hits = [
        p
        for p in paths
        if Path(p).stem.lower() == stem or p[:-3].lower() == q.lower()
    ]
    if not hits:
        return None
    hits.sort(key=len)
    return hits[0]


ROOTS = ("archive", "current", "scratch")  # alphabetical


def _vault_rel(root: str, rel: str) -> str:
    rel = (rel or "").replace("\\", "/").strip("/")
    if root == "current" and _virtual_current("current"):
        return rel
    return f"{root}/{rel}" if rel else root


RAIL_PREVIEW = 4
LIST_PAGE_SIZE = 20


def _root_dir(root: str) -> Path:
    root = (root or "").strip().lower()
    if root not in ROOTS:
        raise HTTPException(status_code=400, detail="root must be archive, current, or scratch")
    vault = vault_path()
    if root == "current":
        physical = vault / "current"
        if physical.is_dir():
            return physical
        return vault
    return vault / root


def _virtual_current(root: str) -> bool:
    return root == "current" and not (vault_path() / "current").is_dir()


def _skip_name(root: str, name: str) -> bool:
    if not _virtual_current(root):
        return False
    return name in ("archive", "scratch")


def list_level(
    root: str,
    rel: str = "",
    *,
    offset: int = 0,
    limit: int = LIST_PAGE_SIZE,
) -> dict:
    """One filesystem position: children of *rel* under *root*, newest first."""
    base = _root_dir(root)
    rel = (rel or "").replace("\\", "/").strip("/")
    if rel:
        if any(p in ("..", "") for p in Path(rel).parts):
            raise HTTPException(status_code=400, detail="bad path")
        here = (base / rel).resolve()
        if not here.is_relative_to(base.resolve()):
            raise HTTPException(status_code=400, detail="outside root")
    else:
        here = base.resolve()
    entries: list[dict] = []
    if here.is_dir():
        for child in here.iterdir():
            if child.name.startswith("."):
                continue
            if _skip_name(root, child.name):
                continue
            try:
                st = child.stat()
            except OSError:
                continue
            kind = "dir" if child.is_dir() else "file"
            if kind == "file" and child.suffix.lower() not in {".md", ".markdown", ".txt"}:
                continue
            rel_child = str((Path(rel) / child.name) if rel else Path(child.name)).replace("\\", "/")
            entries.append(
                {
                    "kind": kind,
                    "name": child.name,
                    "path": rel_child,
                    "vault_path": _vault_rel(root, rel_child),
                    "mtime": int(st.st_mtime),
                    "bytes": int(st.st_size) if kind == "file" else 0,
                }
            )
    entries.sort(key=lambda e: (-int(e["mtime"]), str(e["name"]).lower()))
    off = max(0, int(offset))
    lim = max(1, min(int(limit), 80))
    page = entries[off : off + lim]
    more = off + lim < len(entries)
    return {
        "ok": True,
        "root": root,
        "path": rel,
        "vault_path": _vault_rel(root, rel),
        "offset": off,
        "limit": lim,
        "total": len(entries),
        "more": more,
        "next_offset": off + lim if more else None,
        "entries": page,
    }


def rail() -> dict:
    """Archive / Current / Scratch with a few recent children each."""
    sections = []
    for root in ROOTS:
        listing = list_level(root, "", offset=0, limit=RAIL_PREVIEW)
        sections.append(
            {
                "id": root,
                "label": root.capitalize(),
                "recent": listing["entries"],
                "more": bool(listing["more"] or listing["total"] > RAIL_PREVIEW),
                "total": listing["total"],
            }
        )
    return {"ok": True, "sections": sections}


def list_pages() -> list[dict]:
    vault = vault_path()
    if not vault.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(vault.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".markdown", ".txt"}:
            continue
        rel = str(path.relative_to(vault)).replace("\\", "/")
        out.append(
            {
                "path": rel,
                "name": path.name,
                "bytes": path.stat().st_size,
                "mtime": int(path.stat().st_mtime),
            }
        )
    return out


@router.get("/status")
async def status() -> dict:
    vault = vault_path()
    rustfs = False
    try:
        rustfs = ensure_bucket()
    except Exception:
        rustfs = False
    return {
        "ok": vault.is_dir(),
        "vault": str(vault),
        "rustfs": RUSTFS_URL if rustfs else None,
        "bucket": BUCKET if rustfs else None,
        "prefix": PREFIX,
        "pages": len(list_pages()) if vault.is_dir() else 0,
    }


@router.get("/tree")
async def tree() -> dict:
    pages = list_pages()
    return {"ok": True, "vault": str(vault_path()), "pages": pages}


@router.get("/rail")
async def rail_get() -> dict:
    return rail()


@router.get("/listing")
async def listing(
    root: str,
    path: str = "",
    offset: int = 0,
    limit: int = LIST_PAGE_SIZE,
) -> dict:
    return list_level(root, path, offset=offset, limit=limit)


class PageQuery(BaseModel):
    path: str = Field(min_length=1)


@router.get("/page")
async def page(path: str) -> dict:
    full = _safe(path)
    if not full.is_file():
        raise HTTPException(status_code=404, detail=f"not on disk: {path}")
    text = full.read_text(encoding="utf-8")
    _mirror_put(path, text.encode("utf-8"))
    links = extract_wikilinks(text)
    resolved = []
    pages = list_pages()
    for link in links:
        hit = resolve_wikilink(pages, link["target"])
        resolved.append({**link, "path": hit})
    title = full.stem.replace("-", " ")
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return {
        "ok": True,
        "path": path,
        "title": title,
        "bytes": len(text.encode("utf-8")),
        "text": text,
        "links": resolved,
        "object": f"s3://{BUCKET}/{_object_key(path)}",
    }


@router.get("/resolve")
async def resolve(q: str) -> dict:
    hit = resolve_wikilink(list_pages(), q)
    if not hit:
        raise HTTPException(status_code=404, detail=f"no page for [[{q}]]")
    return {"ok": True, "path": hit, "query": q}


class SyncBody(BaseModel):
    pass


@router.post("/sync")
async def sync() -> dict:
    n = 0
    for entry in list_pages():
        full = _safe(entry["path"])
        _mirror_put(entry["path"], full.read_bytes())
        n += 1
    return {"ok": True, "mirrored": n, "bucket": BUCKET, "prefix": PREFIX}
