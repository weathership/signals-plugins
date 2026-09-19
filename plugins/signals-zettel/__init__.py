"""Slash ``/zettel`` and ``/rtc-review`` → scratch zettels in the Hermes wiki vault.

Filename is ``scratch/YYYY-MM-DD/HHMMSS_slug.md`` under ``OBSIDIAN_VAULT_PATH``
/ ``WIKI_PATH`` / ``${HERMES_HOME}/wiki``. ``/rtc-review`` has Grok review the
last AgentRTC session; next Connect picks that zettel up for ~12 minutes.
"""
from __future__ import annotations

from pathlib import Path

from .capture import capture, format_slash_result, tool_result
from . import review as rtc_review

_SKILL = Path(__file__).resolve().parent / "skills" / "zettel" / "SKILL.md"
_REVIEW_SKILL = Path(__file__).resolve().parent / "skills" / "rtc-review" / "SKILL.md"

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
            "about": {
                "type": "string",
                "description": (
                    "Long-running current/ doc this zettel discusses "
                    "(path or slug). Sets prev/next on the last zettel about it."
                ),
            },
        },
        "required": ["body"],
        "additionalProperties": False,
    },
}

_REVIEW_TOOL = {
    "name": "rtc_review",
    "description": (
        "Have the Hermes Grok subscription review the last AgentRTC session "
        "and file a scratch zettel. Next Connect (~12 minutes) picks it up. "
        "Optional focus, about (current/ doc), session_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "description": "Optional stuck distinction to emphasize.",
            },
            "about": {
                "type": "string",
                "description": "Long-running current/ doc this zettel discusses.",
            },
            "session_id": {
                "type": "string",
                "description": "AgentRTC session id (default: last by activity).",
            },
        },
        "additionalProperties": False,
    },
}


def _slash(raw_args: str) -> str:
    return format_slash_result(capture(body=raw_args or ""))


def _agenda_slash(raw_args: str) -> str:
    from hsengine.engine.agenda_put import put_agenda_item

    text = (raw_args or "").strip()
    if not text:
        return "  usage: /agenda-create <title>"
    prompt = ""
    if " --prompt " in f" {text} ":
        title, _, prompt = text.partition(" --prompt ")
        text = title.strip()
        prompt = prompt.strip()
    intent = "session"
    if text.startswith("--intent "):
        rest = text[len("--intent ") :].strip()
        intent, _, text = rest.partition(" ")
        intent = (intent or "session").strip()
        text = text.strip()
    out = put_agenda_item(
        title=text.split("\n", 1)[0],
        body="\n".join(text.split("\n")[1:]).strip(),
        intent=intent,
        session_prompt=prompt,
        origin_agent="grok",
    )
    if not out.get("ok"):
        return f"  /agenda-create failed: {out.get('error') or out.get('note')}"
    return f"  Agenda {out.get('path') or out.get('id')} ({out.get('origin_agent')})"


def _tool(args: dict, **_kw) -> str:
    return tool_result(
        capture(
            body=str(args.get("body") or ""),
            about=str(args.get("about") or ""),
        )
    )


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
    ctx.register_command(
        "rtc-review",
        handler=rtc_review.slash,
        description=(
            "Grok-review the last AgentRTC session into a scratch zettel "
            "(next Connect pickup)."
        ),
        args_hint="[focus] [--about current/...] [--session id]",
        argument_mode="text",
    )
    ctx.register_command(
        "grok-review",
        handler=rtc_review.slash,
        description=(
            "Alias of /rtc-review: Grok-review the last AgentRTC session "
            "into a scratch zettel."
        ),
        args_hint="[focus] [--about current/...] [--session id]",
        argument_mode="text",
    )
    ctx.register_tool(
        name="rtc_review",
        toolset="signals_zettel",
        schema=_REVIEW_TOOL,
        handler=lambda args, **_k: rtc_review.tool_result(args),
        description=_REVIEW_TOOL["description"],
        emoji="🪞",
    )
    ctx.register_command(
        "agenda-create",
        handler=_agenda_slash,
        description="Create a Gaius Agenda item (session/reminder/brief) as this Hermes profile.",
        args_hint="<title> [--intent session] [--prompt ...]",
        argument_mode="text",
    )
    if _SKILL.is_file():
        ctx.register_skill(
            "zettel",
            _SKILL,
            description="File pasted text as a scratch zettel in the wiki vault.",
        )
    if _REVIEW_SKILL.is_file():
        ctx.register_skill(
            "rtc-review",
            _REVIEW_SKILL,
            description="Grok-review the last AgentRTC session into a scratch zettel.",
        )
