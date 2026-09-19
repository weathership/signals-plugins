"""Origin-project session materials on Signals rustfs.

Bucket ``hermes``, keys ``resources/<zettel-id>/…``. Written when Ripley or
Grok create an Agenda item; fetched at Connect via ServerQuery RESOURCES
against this engine — not stuffed into the Gaius zettel.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("hsengine.engine.resources")

BUCKET = os.environ.get("HERMES_RESOURCES_S3_BUCKET", "hermes")
PREFIX = os.environ.get("HERMES_RESOURCES_S3_PREFIX", "resources").strip("/")
RUSTFS_URL = os.environ.get("SIGNALS_RUSTFS_URL", "http://127.0.0.1:9010")
PROMPT_NAME = "prompt.md"
MATERIALS_NAME = "materials.md"


def _note_stem(note_id: str) -> str:
    rel = (note_id or "").replace("\\", "/").strip().lstrip("/")
    if not rel or any(p in ("..", "") for p in Path(rel).parts):
        return ""
    if rel.endswith(".md"):
        rel = rel[:-3]
    return rel


def resource_prefix(note_id: str) -> str:
    stem = _note_stem(note_id)
    if not stem:
        return ""
    return f"{PREFIX}/{stem}" if PREFIX else stem


def object_uri(note_id: str, name: str) -> str:
    pref = resource_prefix(note_id)
    if not pref:
        return ""
    return f"s3://{BUCKET}/{pref}/{name}"


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
        log.debug("resources rustfs bucket skipped", exc_info=True)
        return False


def put_text(note_id: str, name: str, text: str) -> str:
    """Write one utf-8 object. Returns the s3 uri or ''."""
    pref = resource_prefix(note_id)
    if not pref or not (name or "").strip():
        return ""
    body = (text or "").encode("utf-8")
    if not ensure_bucket():
        return ""
    key = f"{pref}/{name.strip().lstrip('/')}"
    _s3().put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ContentType="text/markdown; charset=utf-8",
    )
    return f"s3://{BUCKET}/{key}"


def put_session_materials(
    note_id: str,
    *,
    prompt: str = "",
    materials: str = "",
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if (prompt or "").strip():
        uri = put_text(note_id, PROMPT_NAME, prompt.strip())
        if uri:
            out.append({"name": PROMPT_NAME, "uri": uri})
    if (materials or "").strip():
        uri = put_text(note_id, MATERIALS_NAME, materials.strip())
        if uri:
            out.append({"name": MATERIALS_NAME, "uri": uri})
    return out


def list_session_materials(note_id: str) -> list[dict[str, Any]]:
    """Read rustfs objects under resources/<note_id>/. Empty list if none."""
    pref = resource_prefix(note_id)
    if not pref:
        return []
    try:
        if not ensure_bucket():
            return []
        client = _s3()
        listed = client.list_objects_v2(Bucket=BUCKET, Prefix=pref.rstrip("/") + "/")
    except Exception:
        log.debug("resources list failed note_id=%s", note_id, exc_info=True)
        return []
    objects: list[dict[str, Any]] = []
    for obj in listed.get("Contents") or []:
        key = str(obj.get("Key") or "")
        name = key.rsplit("/", 1)[-1]
        if not name or name.endswith("/"):
            continue
        try:
            got = client.get_object(Bucket=BUCKET, Key=key)
            raw = got["Body"].read()
            text = raw.decode("utf-8")
        except Exception:
            log.debug("resources get failed key=%s", key, exc_info=True)
            continue
        objects.append(
            {
                "name": name,
                "text": text,
                "uri": f"s3://{BUCKET}/{key}",
            }
        )
    objects.sort(key=lambda r: r["name"])
    return objects
