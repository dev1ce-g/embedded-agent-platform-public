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
            first = subprocess.run(command, encoding="utf-8", capture_output=True, check=False, env=environment)
            second = subprocess.run(command, encoding="utf-8", capture_output=True, check=False, env=environment)

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            result = json.loads(second.stdout)
            self.assertTrue(result["ok"])
            self.assertTrue((prefix / "embedded-agent.cmd").is_file())
            self.assertTrue((prefix / "bin" / "embedded-agent.py").is_file())
            self.assertTrue((prefix / "embedded-agent" / "embedded_agent.py").is_file())
            self.assertTrue((prefix / "config.example.ps1").is_file())
            self.assertTrue((prefix / "jenkins-connections.example.json").is_file())
            self.assertTrue((prefix / "aboot-connections.example.json").is_file())
            self.assertTrue((prefix / "can-runtime" / "can-drivers.example.json").is_file())
            self.assertEqual(
                (ROOT / "VERSION").read_text(encoding="utf-8"),
                (prefix / "VERSION").read_text(encoding="utf-8"),
            )
            registry = json.loads((prefix / "jenkins-connections.example.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["schema_version"], "embedded-jenkins-connections/v1")
            self.assertNotIn("password", json.dumps(registry).lower())
            self.assertNotIn("token", json.dumps(registry).lower())
            # The installer resolves Windows short-name aliases in the prefix.
            self.assertEqual(
                result["jenkins_connections_example"],
                str((prefix / "jenkins-connections.example.json").resolve()),
            )
            aboot_registry = json.loads(
                (prefix / "aboot-connections.example.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                aboot_registry["schema_version"],
                "embedded-aboot-connections/v1",
            )
            can_registry = json.loads(
                (prefix / "can-runtime" / "can-drivers.example.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                can_registry["schema_version"],
                "embedded-can-driver-config/v1",
            )

            environment["EMBEDDED_AGENT_ROOT"] = str(prefix / "attacker-selected-state")
            status = subprocess.run(
                [sys.executable, str(prefix / "bin" / "embedded-agent.py"), "status", "--json"],
                encoding="utf-8",
                capture_output=True,
                check=False,
                env=environment,
            )
            self.assertEqual(0, status.returncode, status.stderr)
            status_value = json.loads(status.stdout)
            self.assertTrue(status_value["ok"])
            self.assertEqual(status_value["root"], str((prefix / "state").resolve()))
            self.assertEqual(
                status_value["platform_version"],
                (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            )


if __name__ == "__main__":
    unittest.main()
