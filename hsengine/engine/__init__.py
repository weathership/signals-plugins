"""Hermes engine — the gRPC daemon that joins the signals lattice.

Federation law (signals-protocol): every engine MUST adopt full-duplex OIP
(server + client proxy + ModelStreamInfer). See
components/signals-protocol/specification/protocol/oip_mandatory.md.

Also register native + zndx.engine.v1 convenience faces (Complete is
DEPRECATED as the sole portable inference path).
"""
from __future__ import annotations


def main() -> None:
    from hsengine.engine.server import main as _main

    _main()
