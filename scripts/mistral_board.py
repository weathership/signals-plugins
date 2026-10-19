# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0
"""Run a Mistral extract from a kanban worker or an ACP session.

Those processes do not carry MISTRAL_API_KEY. The credential is read from
the environment or from HERMES_HOME/.env, the same file the engine uses.
"""

from __future__ import annotations

import argparse
import json
import sys

from hsengine.engine.mistral_agents import api_key
from hsengine.engine.source_drop import classify, mistral_analyze, write_kb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mistral extract for a kanban or ACP process.")
    parser.add_argument("url", help="arXiv, bioRxiv, medRxiv, or other public document URL")
    parser.add_argument("--no-write", action="store_true", help="Analyze only. Do not write the wiki note.")
    args = parser.parse_args(argv)
    if not api_key():
        print("MISTRAL_API_KEY is unset", file=sys.stderr)
        return 1
    kind = classify(args.url)
    source = mistral_analyze(args.url, kind=kind)
    if args.no_write:
        print(json.dumps({k: source[k] for k in ("title", "kind", "scope", "model") if k in source}))
        return 0
    written = write_kb(source)
    print(written.get("relpath") or written.get("path") or "written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
