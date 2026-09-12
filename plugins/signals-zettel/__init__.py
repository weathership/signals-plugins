"""Slash ``/zettel <pasted text>`` → scratch zettel in the Hermes wiki vault.

Filename is ``scratch/YYYY-MM-DD/HHMMSS_slug.md`` under ``OBSIDIAN_VAULT_PATH``
/ ``WIKI_PATH`` / ``${HERMES_HOME}/wiki``. Slug comes from the first line.
"""
from __future__ import annotations

from pathlib import Path

from .capture import capture, format_slash_result, tool_result

_SKILL = Path(__file__).resolve().parent / "skills" / "zettel" / "SKILL.md"

_TOOL = {
    "name": "zettel_capture",
    "description": (
        "Create a scratch zettel in the Hermes wiki vault from pasted text. "
        "Filename slug is the first line. Required: body."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "body": {
                "type": "string",
                "description": "Full note markdown (the pasted text).",
            },
        },
        "required": ["body"],
        "additionalProperties": False,
    },
}


def _slash(raw_args: str) -> str:
    return format_slash_result(capture(body=raw_args or ""))


def _tool(args: dict, **_kw) -> str:
    return tool_result(capture(body=str(args.get("body") or "")))


def register(ctx) -> None:
    ctx.register_command(
        "zettel",
        handler=_slash,
        description="File pasted text as a scratch zettel in the wiki vault.",
        args_hint="<pasted text>",
        argument_mode="text",
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
            description="File pasted text as a scratch zettel in the wiki vault.",
        )
