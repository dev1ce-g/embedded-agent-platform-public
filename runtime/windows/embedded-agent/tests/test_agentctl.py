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

    def test_session_round_trip_is_native_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            started = self.run_agentctl(home, "session", "start", "--task", "test/task", "--workspace", r"D:\work")
            stopped = self.run_agentctl(home, "session", "stop", "--task", "test/task")
            session_path = home / "sessions" / "test_task.json"
            stored = json.loads(session_path.read_text(encoding="utf-8"))
        self.assertEqual(started.returncode, 0)
        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(stored["status"], "stopped")

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

    def test_dispatcher_contains_no_powershell_fallback(self) -> None:
        source = AGENTCTL.read_text(encoding="utf-8")
        self.assertNotIn("powershell", source.lower())
        self.assertNotIn(".ps1", source.lower())


if __name__ == "__main__":
    unittest.main()
