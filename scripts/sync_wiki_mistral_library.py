#!/usr/bin/env python3
"""Sync the Hermes wiki into a Mistral Library.

Markdown under the wiki vault is the library. Unchanged files are skipped.
A changed file replaces its previous document. A file that left the vault
is removed from the library. Documents whose names are not wiki paths are
left alone.

The library id is ``mistral.library_id`` in Hermes config.yaml.
``MISTRAL_API_KEY`` comes from the environment or ``HERMES_HOME/.env``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

LIBRARY_ID_DEFAULT = "01a14b46-d2d4-7425-bb37-47d095e13f22"
_API = "https://api.mistral.ai/v1/libraries"
_SKIP_DIRS = {".obsidian", ".git", "node_modules"}
_MAX_BYTES = 20_000_000

Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, dict[str, Any] | list | None]]


def hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        raw = os.environ.get("HERMES_HOME", "").strip()
        if raw:
            return Path(raw).expanduser()
        return Path.home() / ".hermes"


def vault_root(home: Path | None = None) -> Path:
    for key in ("OBSIDIAN_VAULT_PATH", "WIKI_PATH"):
        raw = os.environ.get(key, "").strip()
        if raw and "${" not in raw:
            return Path(raw).expanduser()
    return (home or hermes_home()) / "wiki"


def library_id(home: Path | None = None) -> str:
    explicit = os.environ.get("MISTRAL_LIBRARY_ID", "").strip()
    if explicit:
        return explicit
    root = home or hermes_home()
    text = ""
    path = root / "config.yaml"
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
    found = _yaml_value(text, ("mistral", "library_id"))
    return found or LIBRARY_ID_DEFAULT


def load_api_key(home: Path | None = None) -> str:
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if key:
        return key
    env_path = (home or hermes_home()) / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "MISTRAL_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def wiki_files(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
        except OSError:
            continue
        found[rel.as_posix()] = path
    return found


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def plan_sync(
    local: dict[str, str],
    remote_by_name: dict[str, dict[str, Any]],
    state: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """Decide uploads, replacements, and deletions from names and hashes.

    ``local`` maps a wiki-relative path to its sha256. ``remote_by_name``
    maps that same path to ``{"id", "hash"}``. ``state`` is the last sync.
    A remote hash equal to the local sha256 is unchanged even without state.
    """
    upload: list[str] = []
    replace: list[str] = []
    delete: list[str] = []
    skip: list[str] = []
    for name, sha in sorted(local.items()):
        remote = remote_by_name.get(name)
        previous = state.get(name) or {}
        remote_hash = str((remote or {}).get("hash") or "")
        if remote and remote_hash and remote_hash == sha:
            skip.append(name)
            continue
        if (
            remote
            and previous.get("sha256") == sha
            and previous.get("document_id") == str(remote.get("id") or "")
        ):
            skip.append(name)
            continue
        if remote:
            replace.append(name)
        else:
            upload.append(name)
    managed = set(state) | set(local)
    for name, remote in remote_by_name.items():
        if name in local or name not in managed:
            continue
        if remote.get("id"):
            delete.append(name)
    return {"upload": upload, "replace": replace, "delete": delete, "skip": skip}


def sync_wiki(
    *,
    root: Path,
    library: str,
    key: str,
    state_path: Path,
    transport: Transport | None = None,
) -> dict[str, Any]:
    if not key:
        raise RuntimeError("MISTRAL_API_KEY is unset")
    if not library:
        raise RuntimeError("Mistral library id is unset")
    send = transport or _http
    local_paths = wiki_files(root)
    local = {name: file_sha256(path) for name, path in local_paths.items()}
    remote = {doc["name"]: doc for doc in _list_documents(library, key, send) if doc.get("name")}
    state = _load_state(state_path)
    actions = plan_sync(local, remote, state.get("files") or {})
    files_state = dict(state.get("files") or {})
    errors: list[str] = []
    for name in actions["delete"]:
        doc_id = str((remote.get(name) or {}).get("id") or "")
        if not doc_id:
            files_state.pop(name, None)
            continue
        try:
            _delete_document(library, doc_id, key, send)
            files_state.pop(name, None)
        except Exception as exc:
            errors.append(f"delete {name}: {exc}")
    for name in actions["replace"] + actions["upload"]:
        previous = str((remote.get(name) or {}).get("id") or "")
        if name in actions["replace"] and previous:
            try:
                _delete_document(library, previous, key, send)
            except Exception as exc:
                errors.append(f"replace-delete {name}: {exc}")
                continue
        try:
            uploaded = _upload_document(library, name, local_paths[name].read_bytes(), key, send)
            doc_id = str(uploaded.get("id") or "")
            if not doc_id:
                raise RuntimeError("upload returned no document id")
            files_state[name] = {"sha256": local[name], "document_id": doc_id}
        except Exception as exc:
            errors.append(f"upload {name}: {exc}")
    for name in actions["skip"]:
        remote_doc = remote.get(name) or {}
        doc_id = str(remote_doc.get("id") or (files_state.get(name) or {}).get("document_id") or "")
        if doc_id:
            files_state[name] = {"sha256": local[name], "document_id": doc_id}
    _save_state(state_path, {"library_id": library, "files": files_state})
    summary = {
        "library_id": library,
        "uploaded": len(actions["upload"]) - _error_count(errors, "upload "),
        "replaced": len(actions["replace"]) - _error_count(errors, "replace-delete "),
        "deleted": len(actions["delete"]) - _error_count(errors, "delete "),
        "skipped": len(actions["skip"]),
        "errors": errors,
    }
    return summary


def _error_count(errors: list[str], prefix: str) -> int:
    return sum(1 for item in errors if item.startswith(prefix))


def _list_documents(library: str, key: str, send: Transport) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    url = f"{_API}/{library}/documents"
    seen: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        status, body = send("GET", url, None, _headers(key))
        if status >= 300 or not isinstance(body, dict):
            raise RuntimeError(f"list documents HTTP {status}")
        for item in body.get("data") or []:
            if isinstance(item, dict):
                docs.append(item)
        pagination = body.get("pagination") or {}
        nxt = pagination.get("next_page") or pagination.get("next") if isinstance(pagination, dict) else None
        url = str(nxt) if nxt else ""
    return docs


def _upload_document(library: str, name: str, content: bytes, key: str, send: Transport) -> dict[str, Any]:
    boundary = f"----HermesWiki{uuid.uuid4().hex}"
    filename = name.replace('"', "")
    preamble = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
    ).encode("utf-8")
    body = preamble + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = _headers(key)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    status, payload = send("POST", f"{_API}/{library}/documents", body, headers)
    if status >= 300 or not isinstance(payload, dict):
        raise RuntimeError(f"HTTP {status}")
    return payload


def _delete_document(library: str, document_id: str, key: str, send: Transport) -> None:
    status, _payload = send(
        "DELETE",
        f"{_API}/{library}/documents/{document_id}",
        None,
        _headers(key),
    )
    if status >= 300:
        raise RuntimeError(f"HTTP {status}")


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _http(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, {"detail": raw.decode("utf-8", "replace")[:300]}


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"files": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"files": {}}
    if not isinstance(payload, dict):
        return {"files": {}}
    payload.setdefault("files", {})
    return payload


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _yaml_value(text: str, path: tuple[str, ...]) -> str:
    """Read one nested scalar. Enough for ``mistral.library_id``."""
    want = list(path)
    depth = 0
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        name, _, value = raw.strip().partition(":")
        value = value.strip().strip('"').strip("'")
        if indent == 0:
            depth = 0
        if depth < len(want) and name == want[depth] and indent == depth * 2:
            if depth == len(want) - 1:
                return value
            depth += 1
    return ""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in args
    home = hermes_home()
    root = vault_root(home)
    library = library_id(home)
    key = load_api_key(home)
    if not key:
        print("MISTRAL_API_KEY is unset", file=sys.stderr)
        return 2
    state_path = home / "cache" / "mistral-wiki-library.json"
    if dry_run:
        local = {name: file_sha256(path) for name, path in wiki_files(root).items()}
        print(f"library={library} files={len(local)} vault={root}")
        return 0
    try:
        summary = sync_wiki(root=root, library=library, key=key, state_path=state_path)
    except Exception as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    print(
        "mistral wiki sync "
        f"uploaded={summary['uploaded']} replaced={summary['replaced']} "
        f"deleted={summary['deleted']} skipped={summary['skipped']} "
        f"errors={len(summary['errors'])}"
    )
    for item in summary["errors"][:20]:
        print(f"error: {item}", file=sys.stderr)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
