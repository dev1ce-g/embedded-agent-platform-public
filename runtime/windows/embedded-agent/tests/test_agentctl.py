from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_HOME = Path(__file__).resolve().parents[2]
AGENTCTL = AGENT_HOME / "bin" / "agentctl.py"


class AgentctlTests(unittest.TestCase):
    def run_agentctl(self, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["EMBEDDED_AGENT_HOME"] = str(home)
        return subprocess.run(
            [sys.executable, str(AGENTCTL), *arguments, "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env=environment,
        )

    def test_status_reports_python_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_agentctl(Path(directory), "status")
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(value["ok"])
        self.assertEqual(value["dispatcher"], "python")
        self.assertNotIn("sessions", value)

    def test_workflow_session_store_is_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            completed = self.run_agentctl(home, "session", "start", "--task", "test/task", "--workspace", r"D:\work")
            session_store_created = (home / "sessions").exists()
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(value["operation"], "agentctl")
        self.assertIn("Unknown subcommand", value["first_failure"])
        self.assertFalse(session_store_created)

    def test_mpu_flash_is_not_routed_to_platform_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_agentctl(
                Path(directory),
                "flash",
                "mpu",
                "--require-confirm",
                "--confirm",
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 4)
        self.assertIn("Python Runtime", value["first_failure"])

    def test_mcu_flash_requires_discovered_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_agentctl(
                Path(directory),
                "flash",
                "mcu",
                "--workspace",
                directory,
                "--require-confirm",
                "--confirm",
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--project-path", value["first_failure"])

    def test_mcu_build_requires_discovered_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_agentctl(
                Path(directory),
                "build",
                "mcu",
                "--workspace",
                directory,
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--project-path", value["first_failure"])

    def test_rtt_reset_requires_confirmation_before_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_agentctl(
                Path(directory),
                "rtt",
                "capture",
                "--workspace",
                directory,
                "--reset",
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertTrue(value["requires_human_confirm"])
        self.assertEqual(value["gate"]["level"], "L3")
        self.assertFalse(value["gate"]["confirmed"])
        self.assertEqual(value["error"]["code"], "INVALID_REQUEST")

    def test_dispatcher_contains_no_powershell_fallback(self) -> None:
        source = AGENTCTL.read_text(encoding="utf-8")
        self.assertNotIn("powershell", source.lower())
        self.assertNotIn(".ps1", source.lower())

    def test_artifact_latest_ignores_external_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "secret.bin"
            outside.write_bytes(b"must-not-be-hashed")
            try:
                (workspace / "latest.bin").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            completed = self.run_agentctl(
                home,
                "artifact",
                "latest",
                "--workspace",
                str(workspace),
            )

        value = json.loads(completed.stdout)
        self.assertEqual(1, completed.returncode)
        self.assertFalse(value["ok"])
        self.assertIsNone(value["artifact"])


if __name__ == "__main__":
    unittest.main()
