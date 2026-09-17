"""HoloViews on the AgentRTC video track.

Bishop/Ripley/Vasquez call viz_show; the live Chromium compositor is the
video. Nested Hermes gets the same tools. HoloViews is required on the
engine. Datashader is not this pass.
"""
from __future__ import annotations

import json
from pathlib import Path

_SKILL = Path(__file__).resolve().parent / "skills" / "holoviews-viz" / "SKILL.md"

_SHOW = {
    "name": "viz_show",
    "description": (
        "Put a live HoloViews/Bokeh page on the AgentRTC video "
        "(headless Chromium + CDP screencast). Humans spectate; agents "
        "drive. kind=chord|aperture|scatter|curve|heatmap. Aegir is "
        "optional data, not required. Do not describe the figure as "
        "on-screen until this returns ok."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "chord, aperture, scatter, curve, or heatmap.",
            },
            "title": {"type": "string", "description": "Title on the live figure."},
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
        "Highlight a node on the live AgentRTC video figure. "
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

_HOVER = {
    "name": "viz_hover",
    "description": (
        "Hover the live HoloViews figure so Bokeh popups follow the narrative. "
        "lane=SLB. t=0..1 along time."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lane": {"type": "string"},
            "node": {"type": "string"},
            "t": {"type": "number"},
            "at": {"type": "string"},
        },
        "additionalProperties": False,
    },
}

_INPUT = {
    "name": "viz_input",
    "description": (
        "Agent pointer on the live HoloViews page (CSS pixels, 1280x720). "
        "Spectators cannot drive this."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "type": {"type": "string"},
            "button": {"type": "string"},
        },
        "required": ["x", "y"],
        "additionalProperties": False,
    },
}

_CLEAR = {
    "name": "viz_clear",
    "description": "Take the live HoloViews page off the video and restore the looping clip.",
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


def _hover(args: dict, **_kw) -> str:
    from hsengine.engine import webrtc_viz

    t = args.get("t")
    try:
        frac = float(t) if t not in (None, "") else None
    except (TypeError, ValueError):
        frac = None
    return json.dumps(
        webrtc_viz.hover(
            lane=str(args.get("lane") or args.get("node") or ""),
            t=frac,
            at=str(args.get("at") or ""),
        )
    )


def _input(args: dict, **_kw) -> str:
    from hsengine.engine import webrtc_viz

    try:
        x = float(args.get("x"))
        y = float(args.get("y"))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "x and y are required"})
    return json.dumps(
        webrtc_viz.pointer(
            x=x,
            y=y,
            type=str(args.get("type") or "mousePressed"),
            button=str(args.get("button") or "left"),
        )
    )


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
        name="viz_hover",
        toolset="signals_holoviews",
        schema=_HOVER,
        handler=_hover,
        description=_HOVER["description"],
        emoji="◎",
    )
    ctx.register_tool(
        name="viz_input",
        toolset="signals_holoviews",
        schema=_INPUT,
        handler=_input,
        description=_INPUT["description"],
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
