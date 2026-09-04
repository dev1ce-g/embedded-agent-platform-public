from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "runtime" / "windows" / "install.py"


class WindowsRuntimeInstallerTests(unittest.TestCase):
    def test_installs_a_relocatable_runtime_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "工具 runtime"
            command = [sys.executable, str(INSTALLER), "--prefix", str(prefix), "--json"]
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "cp1252"
            first = subprocess.run(command, text=True, capture_output=True, check=False, env=environment)
            second = subprocess.run(command, text=True, capture_output=True, check=False, env=environment)

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            result = json.loads(second.stdout)
            self.assertTrue(result["ok"])
            self.assertTrue((prefix / "embedded-agent.cmd").is_file())
            self.assertTrue((prefix / "bin" / "embedded-agent.py").is_file())
            self.assertTrue((prefix / "embedded-agent" / "embedded_agent.py").is_file())
            self.assertTrue((prefix / "config.example.ps1").is_file())

            environment["EMBEDDED_AGENT_ROOT"] = str(prefix / "state")
            status = subprocess.run(
                [sys.executable, str(prefix / "bin" / "embedded-agent.py"), "status", "--json"],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertTrue(json.loads(status.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
