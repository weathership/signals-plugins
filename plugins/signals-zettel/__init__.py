"""Clipboard → scratch zettel in the Hermes wiki vault.

Slash ``/zettel [title]`` reads the host clipboard and writes
``scratch/YYYY-MM-DD/HHMMSS_slug.md`` under ``OBSIDIAN_VAULT_PATH`` /
``WIKI_PATH`` / ``${HERMES_HOME}/wiki``.
"""
from __future__ import annotations

from pathlib import Path

from .capture import capture, format_slash_result, tool_result

_SKILL = Path(__file__).resolve().parent / "skills" / "zettel" / "SKILL.md"

_TOOL = {
    "name": "zettel_capture",
    "description": (
        "Create a scratch zettel in the Hermes wiki vault from clipboard "
        "text (or an explicit body). One shot: filename + content."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Note title / slug. Default: first heading or line of the body.",
            },
            "body": {
                "type": "string",
                "description": "Note markdown. Omit to read the host clipboard.",
            },
        },
        "additionalProperties": False,
    },
}


def _slash(raw_args: str) -> str:
    title = (raw_args or "").strip()
    return format_slash_result(capture(title=title))


def _tool(args: dict, **_kw) -> str:
    title = str(args.get("title") or "")
    body = args.get("body")
    if body is not None:
        body = str(body)
    return tool_result(capture(title=title, body=body))


def register(ctx) -> None:
    ctx.register_command(
        "zettel",
        handler=_slash,
        description="File clipboard text as a scratch zettel in the wiki vault.",
        args_hint="[title]",
    )
    ctx.register_tool(
        name="zettel_capture",
        toolset="signals_zettel",
        schema=_TOOL,
        handler=_tool,
        description=_TOOL["description"],
        emoji="📝",
    )
    if _SKILL.is_file():
        ctx.register_skill(
            "zettel",
            _SKILL,
            description="File a clipboard zettel into the Hermes wiki vault.",
        )
