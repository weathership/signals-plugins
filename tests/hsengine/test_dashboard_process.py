"""Dashboard process wrapper — non-loopback bind + secretspec auth."""
from __future__ import annotations

import os
import stat
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/processes/hermes-dashboard.sh"


class DashboardProcessTests(unittest.TestCase):
    def test_wrapper_is_executable(self) -> None:
        self.assertTrue(SCRIPT.is_file())
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)

    def test_refuses_to_start_without_password(self) -> None:
        env = os.environ.copy()
        env.pop("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", None)
        env.pop("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH", None)
        env["HERMES_DASHBOARD_BASIC_AUTH_USERNAME"] = "hermes"
        env["HERMES_DASHBOARD_IGNORE_DOTENV"] = "1"
        proc = subprocess.run(
            [str(SCRIPT)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DENY", proc.stderr)
        self.assertIn("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", proc.stderr)


if __name__ == "__main__":
    unittest.main()
