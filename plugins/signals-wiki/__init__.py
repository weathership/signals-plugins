"""Signals wiki — dashboard tab over the Hermes vault, mirrored to rustfs."""

from __future__ import annotations

import json
from pathlib import Path

_SKILL = Path(__file__).resolve().parent / "skills" / "wiki-kasten" / "SKILL.md"


def _setup_wiki_cli(parser) -> None:
    sub = parser.add_subparsers(dest="wiki_cmd")
    arch = sub.add_parser(
        "archive-scratch",
        help="Move fortnight-old scratch zettels to archive/YYYYQN/MM-DD/",
    )
    arch.add_argument("--dry-run", action="store_true")
    arch.add_argument("--days", type=int, default=14)
    arch.add_argument("--install-cron", action="store_true")


def _wiki_cli(args) -> int:
    from .archive_scratch import ensure_cron_job, migrate

    if getattr(args, "wiki_cmd", None) != "archive-scratch":
        print("usage: hermes wiki archive-scratch [--dry-run] [--install-cron]")
        return 2
    if args.install_cron:
        print(json.dumps(ensure_cron_job()))
        return 0
    print(json.dumps(migrate(days=args.days, dry_run=args.dry_run), indent=2))
    return 0


def register(ctx) -> None:
    if _SKILL.is_file():
        ctx.register_skill(
            "wiki-kasten",
            _SKILL,
            description="File long-running wiki docs and chained scratch zettels.",
        )
    ctx.register_cli_command(
        name="wiki",
        help="Hermes wiki kasten (archive-scratch)",
        setup_fn=_setup_wiki_cli,
        handler_fn=_wiki_cli,
        description="Archive fortnight-old scratch zettels; rewrite prev/next.",
    )
    try:
        from .archive_scratch import ensure_cron_job

        ensure_cron_job()
    except Exception:
        pass
    try:
        import importlib.util

        loc = Path(__file__).resolve().parent / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location("signals_wiki_plugin_api", loc)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ensure_bucket()
    except Exception:
        return
