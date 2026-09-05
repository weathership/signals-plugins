"""install.sh links plugin dirs into a temp HERMES_HOME."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "scripts" / "install.sh"
INSTALL_GH = REPO / "scripts" / "install-from-github.sh"
PLUGINS = ("signals-oip", "signals-memory", "signals-compact")


class InstallTests(unittest.TestCase):
    def test_install_script_is_executable_and_valid(self) -> None:
        self.assertTrue(INSTALL.is_file())
        self.assertTrue(os.access(INSTALL, os.X_OK))
        subprocess.run(["bash", "-n", str(INSTALL)], check=True)
        self.assertTrue(INSTALL_GH.is_file())
        self.assertTrue(os.access(INSTALL_GH, os.X_OK))
        subprocess.run(["bash", "-n", str(INSTALL_GH)], check=True)

    def test_install_symlinks_and_is_idempotent(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            env = {**os.environ, "HERMES_HOME": str(home)}
            env.pop("HERMES_PROFILE", None)
            subprocess.run([str(INSTALL), "--quiet"], check=True, env=env)
            for name in PLUGINS:
                dest = home / "plugins" / name
                self.assertTrue(dest.is_symlink(), name)
                self.assertEqual((REPO / "plugins" / name).resolve(), dest.resolve())
                self.assertTrue((dest / "plugin.yaml").is_file())
            subprocess.run([str(INSTALL), "--quiet"], check=True, env=env)
            subprocess.run([str(INSTALL), "--uninstall", "--quiet"], check=True, env=env)
            for name in PLUGINS:
                self.assertFalse((home / "plugins" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
