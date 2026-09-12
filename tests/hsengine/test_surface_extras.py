"""Hold the line: devenv extras are Signals-owned, not upstream Hermes."""
from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsengine.surface import LOCAL_EXTRAS  # noqa: E402

DEVENV_NIX = ROOT / "devenv.nix"
PYPROJECT = ROOT / "pyproject.toml"

_EXTRAS_RE = re.compile(r"extras\s*=\s*\[([^\]]*)\]", re.S)
_ALL_EXTRAS_RE = re.compile(r"allExtras\s*=\s*true")


def _devenv_extras() -> list[str]:
    text = DEVENV_NIX.read_text(encoding="utf-8")
    if _ALL_EXTRAS_RE.search(text):
        raise AssertionError("devenv.nix must not set uv.sync.allExtras = true")
    match = _EXTRAS_RE.search(text)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


def _optional_extra_names() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return set((data.get("project") or {}).get("optional-dependencies") or {})


def _all_extra_includes() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    extras = (data.get("project") or {}).get("optional-dependencies") or {}
    return list(extras.get("all") or [])


class SurfaceExtrasTests(unittest.TestCase):
    def test_devenv_extras_are_local_only(self) -> None:
        got = set(_devenv_extras())
        unknown = got - LOCAL_EXTRAS
        self.assertFalse(
            unknown,
            f"devenv.nix uv extras {sorted(unknown)} are not in LOCAL_EXTRAS "
            f"{sorted(LOCAL_EXTRAS)} — do not pull upstream Hermes extras",
        )
        self.assertNotIn("all", got)

    def test_local_extras_exist_in_pyproject(self) -> None:
        names = _optional_extra_names()
        missing = LOCAL_EXTRAS - names
        self.assertFalse(
            missing,
            f"LOCAL_EXTRAS {sorted(missing)} missing from "
            "[project.optional-dependencies]",
        )

    def test_signals_extra_includes_engine_and_nautilus(self) -> None:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        extras = (data.get("project") or {}).get("optional-dependencies") or {}
        signals = list(extras.get("signals") or [])
        self.assertIn("hermes-agent[engine]", signals)
        self.assertTrue(
            any("nautilus" in str(item) for item in signals),
            f"signals extra must include nautilus, got {signals}",
        )

    def test_upstream_all_does_not_swallow_local_extras(self) -> None:
        includes = _all_extra_includes()
        swallowed = [
            item
            for extra in LOCAL_EXTRAS
            for item in includes
            if extra in item.split("[")[-1]
        ]
        self.assertFalse(
            swallowed,
            f"[all] must stay the upstream Hermes bundle; remove {swallowed}",
        )


if __name__ == "__main__":
    unittest.main()
