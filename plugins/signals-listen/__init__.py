"""Signals listen — dashboard WebRTC viewer of hsengine AgentRTC.

Dashboard tab + plugin_api.py are the UI. The engine sidecar is the
``signals-hsengine`` extra (``python -m hsengine``). Enable this plugin
in config.yaml so the dashboard mounts plugin_api.

If hsengine is installed, register its session overlay so Hermes proper
and delegate_task children use Cerebras while an interactive Activity
is in force — without Hermes core importing AgentRTC by name.
"""


def register(ctx) -> None:
    try:
        from hsengine.overlay import overlay_runtime
    except ImportError:
        return
    ctx.register_session_runtime_overlay(overlay_runtime)
