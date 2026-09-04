from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent
import embedded_runtime_tools


class ToolProxyTests(unittest.TestCase):
    project = "test-project"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.root = self.base / "agent"
        self.workspace = self.base / "workspace"
        self.repo = self.workspace / "mcu"
        (self.repo / "project").mkdir(parents=True)
        project_dir = self.root / "projects" / self.project
        project_dir.mkdir(parents=True)
        self.background = {
            "project_id": self.project,
            "background_id": "bg-1",
            "workspace": str(self.workspace),
        }
        (project_dir / "background.json").write_text(json.dumps(self.background), encoding="utf-8")

        self.source = self.repo / "project" / "demo.c"
        self.source.write_text("int value = 1;\n", encoding="utf-8")
        self.git("init")
        self.git("config", "user.email", "agent@example.test")
        self.git("config", "user.name", "Embedded Agent Test")
        self.git("add", "project/demo.c")
        self.git("commit", "-m", "baseline")
        self.source.write_text("int value = 2;\n", encoding="utf-8")

    def git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def call(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(["--root", str(self.root), *arguments, "--json"])
        return exit_code, json.loads(output.getvalue())

    def test_git_diff_honors_explicit_root_with_project_path(self) -> None:
        exit_code, value = self.call(
            "git",
            "diff",
            "--project",
            self.project,
            "--root",
            "mcu",
            "--path",
            "mcu/project/demo.c",
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["repo_path"], "mcu")
        self.assertIn("int value = 2", value["diff"])

    def test_python_search_can_scan_beyond_default_window_when_requested(self) -> None:
        large_log = self.repo / "large.log"
        large_log.write_bytes(b"a" * (embedded_agent.DEFAULT_TOOL_SEARCH_BYTES + 128) + b"\nneedle\n")
        with mock.patch.object(embedded_runtime_tools, "run_ripgrep", return_value=None):
            exit_code, value = self.call(
                "tool",
                "rg",
                "--project",
                self.project,
                "--root",
                "mcu/large.log",
                "--pattern",
                "needle",
                "--max-bytes",
                str(2 * embedded_agent.DEFAULT_TOOL_SEARCH_BYTES),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["match_count"], 1)
        self.assertFalse(value["truncated"])
        self.assertGreater(value["bytes_read"], embedded_agent.DEFAULT_TOOL_SEARCH_BYTES)


if __name__ == "__main__":
    unittest.main()
