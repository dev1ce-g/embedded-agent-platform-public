from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent


class LogArtifactCommandTests(unittest.TestCase):
    project = "test-project"
    task = "06-08-uds-tester-mcu-soc-deploy"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.root = self.base / "agent"
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        project_dir = self.root / "projects" / self.project
        project_dir.mkdir(parents=True)
        (project_dir / "background.json").write_text(
            json.dumps(
                {
                    "project_id": self.project,
                    "background_id": "bg-1",
                    "workspace": str(self.workspace),
                }
            ),
            encoding="utf-8",
        )
        self.desktop = self.base / "Desktop"
        self.desktop.mkdir()

    def call(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(["--root", str(self.root), *arguments, "--json"])
        return exit_code, json.loads(output.getvalue())

    def import_args(self, source: Path, confirm: bool = True) -> list[str]:
        args = [
            "log",
            "import",
            "--project",
            self.project,
            "--task",
            self.task,
            "--label",
            "mcu",
            "--source",
            str(source),
        ]
        if confirm:
            args.append("--confirm")
        return args

    def import_log(self, source: Path) -> dict:
        with mock.patch.dict(os.environ, {"EMBEDDED_AGENT_LOG_IMPORT_ROOTS": str(self.desktop)}, clear=False):
            exit_code, value = self.call(*self.import_args(source))
        self.assertEqual(exit_code, 0)
        self.assertTrue(value["verified"])
        return value

    def test_confirmation_gate_precedes_desktop_source_read(self) -> None:
        source = self.desktop / "mcu.txt"
        source.write_text("request_id=42\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"EMBEDDED_AGENT_LOG_IMPORT_ROOTS": str(self.desktop)}, clear=False):
            exit_code, value = self.call(*self.import_args(source, confirm=False))
        self.assertEqual(exit_code, 3)
        self.assertFalse(value["gate"]["confirmed"])
        self.assertFalse((self.root / "projects" / self.project / "artifacts" / "logs").exists())

    def test_rejects_source_outside_configured_import_root(self) -> None:
        source = self.base / "not-desktop.txt"
        source.write_text("timeout\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"EMBEDDED_AGENT_LOG_IMPORT_ROOTS": str(self.desktop)}, clear=False):
            exit_code, value = self.call(*self.import_args(source))
        self.assertEqual(exit_code, 5)
        self.assertIn("outside", value["first_failure"])

    def test_imports_immutable_artifact_and_serves_bounded_queries(self) -> None:
        source = self.desktop / "mcu.txt"
        source.write_text(
            "10:00:00 Tx request_id=42 SID=0x22\n"
            "10:00:01 Rx request_id=42 NRC=0x78\n"
            "10:00:02 ERROR timeout request_id=42\n",
            encoding="utf-8",
        )
        imported = self.import_log(source)
        artifact = imported["artifact_id"]
        self.assertEqual(imported["line_count"], 3)
        self.assertEqual(source.read_text(encoding="utf-8").count("\n"), 3)

        exit_code, stat = self.call("log", "stat", "--project", self.project, "--artifact", artifact)
        self.assertEqual(exit_code, 0)
        self.assertTrue(stat["integrity_verified"])
        self.assertEqual(stat["sha256"], imported["sha256"])

        exit_code, read = self.call("log", "read", "--project", self.project, "--artifact", artifact, "--max-bytes", "64")
        self.assertEqual(exit_code, 0)
        self.assertIn("request_id=42", read["content"])
        self.assertTrue(read["truncated"])

        exit_code, matches = self.call(
            "log",
            "rg",
            "--project",
            self.project,
            "--artifact",
            artifact,
            "--pattern",
            "timeout",
            "--ignore-case",
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(matches["match_count"], 1)
        self.assertEqual(matches["matches"][0]["line"], 3)

        exit_code, context = self.call(
            "log",
            "context",
            "--project",
            self.project,
            "--artifact",
            artifact,
            "--line",
            "3",
            "--before",
            "2",
            "--after",
            "0",
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(context["start_line"], 1)
        self.assertEqual(context["end_line"], 3)
        self.assertEqual(len(context["lines"]), 3)

    def test_artifact_identifier_cannot_escape_private_store(self) -> None:
        exit_code, value = self.call("log", "stat", "--project", self.project, "--artifact", "../outside")
        self.assertEqual(exit_code, 2)
        self.assertEqual(value["first_failure"], "Invalid log artifact id")

    def test_json_transport_round_trips_chinese_text(self) -> None:
        payload = {"message": "预刷写读取ECU版本"}
        encoded = embedded_agent.json_dump(payload)
        self.assertEqual(json.loads(encoded), payload)


if __name__ == "__main__":
    unittest.main()
