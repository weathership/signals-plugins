"""HOCON config loader — the only sanctioned config entry point.

House rule: env vars enter through ``${?VAR}`` capture in config/base.conf;
application code reads ``load_config()``, never ``os.environ``.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory, ConfigTree

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def load_config(config_dir: Path | None = None) -> ConfigTree:
    """Parse ``base.conf``. Re-reads when the file's mtime changes.

    The engine is a long-lived devenv process; voice (and other) edits must
    take effect without a restart.
    """
    base = (config_dir or _DEFAULT_CONFIG_DIR) / "base.conf"
    try:
        mtime = base.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _load_config_at(str(base), mtime)


@functools.lru_cache(maxsize=8)
def _load_config_at(base: str, mtime: float) -> ConfigTree:
    return ConfigFactory.parse_file(base, resolve=True)


def get_config() -> ConfigTree:
    return load_config()


def get_str(path: str) -> str:
    return str(load_config().get(path))


def get_int(path: str) -> int:
    return int(str(load_config().get(path)))


def get_list(path: str) -> list[Any]:
    value = load_config().get(path)
    if value is None:
        return []
    return list(value)


def reset_config() -> None:
    _load_config_at.cache_clear()
