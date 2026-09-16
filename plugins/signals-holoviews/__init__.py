"""HoloViews program stills on the AgentRTC video track.

Renders on the engine (same process as WebRTC). Bishop/Ripley call viz_show
to fade the looping clip out and a chord/scatter/curve in. Nested Hermes
gets the same tools. HoloViews is required on the engine. Datashader is not this pass.
"""
from __future__ import annotations

import json
from pathlib import Path

_SKILL = Path(__file__).resolve().parent / "skills" / "holoviews-viz" / "SKILL.md"

_SHOW = {
    "name": "viz_show",
    "description": (
        "Fade a scientific visualization onto the AgentRTC video feed "
        "(HoloViews/matplotlib, server-side). kind=chord|aperture|scatter|"
        "curve|heatmap. source=aegir loads the SKOS aperture chord when "
        "Aegir is importable. highlight names a node to emphasize. "
        "Do not describe the figure as shown until this tool returns ok."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "chord, aperture, scatter, curve, or heatmap.",
            },
            "title": {"type": "string", "description": "Title burned onto the still."},
            "highlight": {
                "type": "string",
                "description": "Node/label to emphasize on a chord.",
            },
            "source": {
                "type": "string",
                "description": "aegir for the live SKOS aperture; demo otherwise.",
            },
            "data": {
                "type": "string",
                "description": "Optional JSON {nodes, edges} for a custom chord.",
            },
            "fade_s": {
                "type": "number",
                "description": "Fade duration in seconds (default 0.7).",
            },
        },
        "additionalProperties": False,
    },
}

_SELECT = {
    "name": "viz_select",
    "description": (
        "Re-render the current AgentRTC program still with a node highlighted. "
        "Use after viz_show to drill into an ontology arc or data feature."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "node": {"type": "string", "description": "Node/label to highlight."},
        },
        "required": ["node"],
        "additionalProperties": False,
    },
}

_CLEAR = {
    "name": "viz_clear",
    "description": "Fade the program still out and restore the looping AgentRTC clip.",
    "parameters": {
        "type": "object",
        "properties": {
            "fade_s": {"type": "number", "description": "Fade duration in seconds."},
        },
        "additionalProperties": False,
    },
}


def _show(args: dict, **_kw) -> str:
    from hsengine.engine import webrtc_program

    fade = args.get("fade_s")
    try:
        fade_s = float(fade) if fade not in (None, "") else 0.7
    except (TypeError, ValueError):
        fade_s = 0.7
    return json.dumps(
        webrtc_program.show(
            kind=str(args.get("kind") or "chord"),
            title=str(args.get("title") or ""),
            highlight=str(args.get("highlight") or ""),
            source=str(args.get("source") or ""),
            data=str(args.get("data") or ""),
            fade_s=fade_s,
        )
    )


def _select(args: dict, **_kw) -> str:
    from hsengine.engine import webrtc_program

    return json.dumps(webrtc_program.select(node=str(args.get("node") or "")))


def _clear(args: dict, **_kw) -> str:
    from hsengine.engine import webrtc_program

    fade = args.get("fade_s")
    try:
        fade_s = float(fade) if fade not in (None, "") else 0.7
    except (TypeError, ValueError):
        fade_s = 0.7
    return json.dumps(webrtc_program.clear(fade_s=fade_s))


def register(ctx) -> None:
    from hsengine.engine import webrtc_program
    from .render import render_scene

    webrtc_program.register_renderer(render_scene)
    ctx.register_tool(
        name="viz_show",
        toolset="signals_holoviews",
        schema=_SHOW,
        handler=_show,
        description=_SHOW["description"],
        emoji="◎",
    )
    ctx.register_tool(
        name="viz_select",
        toolset="signals_holoviews",
        schema=_SELECT,
        handler=_select,
        description=_SELECT["description"],
        emoji="◎",
    )
    ctx.register_tool(
        name="viz_clear",
        toolset="signals_holoviews",
        schema=_CLEAR,
        handler=_clear,
        description=_CLEAR["description"],
        emoji="◎",
    )
    if _SKILL.is_file():
        ctx.register_skill(
            "holoviews-viz",
            _SKILL,
            description="Drive HoloViews stills on the AgentRTC video feed.",
        )
