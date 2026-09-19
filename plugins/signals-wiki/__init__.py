"""Signals wiki — dashboard tab over the Hermes vault, mirrored to rustfs."""

from pathlib import Path


def register(ctx) -> None:
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
