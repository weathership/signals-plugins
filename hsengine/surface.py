"""Local operational surface — perihelion.

The Signals stack may grow extras of *our* own. Upstream Hermes extras
(``[all]``, ``web``, ``google``, ``youtube``, ``mcp``, messaging, …) and
in-tree plugins stay off the devenv venv. Expand ``LOCAL_EXTRAS`` only when
a lattice/Signals capability needs a dedicated extra; never to pull an
upstream agent extra.
"""

from __future__ import annotations

# Allowlisted uv extras for devenv.nix languages.python.uv.sync.extras.
# `signals` composes the lattice engine + Nautilus. Do not list `engine`
# here — it is an internal extra, not a devenv extra.
LOCAL_EXTRAS = frozenset({"signals"})
