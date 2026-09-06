"""Signals listen — dashboard WebRTC viewer of hsengine forward-sim.

CLI/gateway hooks are empty; the dashboard tab + plugin_api.py are the
surface. Enable in config.yaml so the dashboard mounts plugin_api
(user plugins are not imported until listed in plugins.enabled).
"""


def register(ctx) -> None:
    return
