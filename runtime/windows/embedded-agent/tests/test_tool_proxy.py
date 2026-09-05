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
import embedded_runtime_common
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

    def test_default_state_root_load_uses_machine_workspace_boundary(self) -> None:
        machine_workspaces = self.base / "machine-workspaces"
        machine_workspaces.mkdir()
        with (
            mock.patch.object(embedded_runtime_common, "DEFAULT_ROOT", self.root),
            mock.patch.object(
                embedded_runtime_common,
                "DEFAULT_WORKSPACE_ROOT",
                machine_workspaces,
            ),
        ):
            paths = embedded_runtime_common.agent_paths(self.root)
            background = embedded_runtime_common.read_background(paths, self.project)

        self.assertEqual(machine_workspaces, paths.workspace_root)
        self.assertIsNone(background)

    def test_custom_state_root_uses_parent_test_boundary(self) -> None:
        paths = embedded_runtime_common.agent_paths(self.root)

        self.assertEqual(self.root.parent.resolve(), paths.workspace_root)

    def test_tool_load_rejects_rebound_workspace(self) -> None:
        outside_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_directory.cleanup)
        outside = Path(outside_directory.name)
        secret = "REBOUND_WORKSPACE_SECRET_3d8a"
        (outside / "secret.txt").write_text(secret, encoding="utf-8")

        original_workspace = self.base / "original-workspace"
        self.workspace.rename(original_workspace)
        try:
            self.workspace.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        exit_code, value = self.call(
            "tool",
            "read",
            "--project",
            self.project,
            "--path",
            "secret.txt",
        )

        self.assertEqual(2, exit_code)
        self.assertFalse(value["ok"])
        self.assertEqual("Project background not found", value["first_failure"])
        self.assertNotIn(secret, json.dumps(value))

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

    def test_git_show_rejects_option_injection_before_execution(self) -> None:
        escaped = self.base / "escaped-output"
        exit_code, value = self.call(
            "git",
            "show",
            "--project",
            self.project,
            "--root",
            "mcu",
            f"--rev=--output={escaped}",
        )
        self.assertEqual(2, exit_code)
        self.assertFalse(value["ok"])
        self.assertFalse(escaped.exists())

    def test_git_show_resolves_revision_to_exact_commit(self) -> None:
        exit_code, value = self.call(
            "git",
            "show",
            "--project",
            self.project,
            "--root",
            "mcu",
            "--rev",
            "HEAD",
            "--no-patch",
        )
        self.assertEqual(0, exit_code, value)
        self.assertRegex(value["commit"], r"^[0-9a-f]{40}$")

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

    def test_python_search_does_not_read_external_file_symlink(self) -> None:
        secret = "EXTERNAL_FILE_SECRET_7a9d"
        outside = self.base / "outside-secret.txt"
        outside.write_text(secret, encoding="utf-8")
        linked = self.repo / "project" / "linked-secret.txt"
        try:
            linked.symlink_to(outside)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"file symlinks are unavailable: {exc}")

        with mock.patch.object(embedded_runtime_tools, "run_ripgrep", return_value=None):
            exit_code, value = self.call(
                "tool",
                "rg",
                "--project",
                self.project,
                "--root",
                "mcu",
                "--pattern",
                "EXTERNAL_FILE_SECRET",
            )

        self.assertEqual(exit_code, 0, value)
        self.assertEqual(value["backend"], "python-fallback")
        self.assertEqual(value["match_count"], 0)
        self.assertNotIn(secret, json.dumps(value))

    def test_python_search_does_not_enter_external_directory_symlink(self) -> None:
        secret = "EXTERNAL_DIRECTORY_SECRET_d4c1"
        outside = self.base / "outside-directory"
        outside.mkdir()
        (outside / "secret.txt").write_text(secret, encoding="utf-8")
        linked = self.repo / "project" / "linked-directory"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        with mock.patch.object(embedded_runtime_tools, "run_ripgrep", return_value=None):
            exit_code, value = self.call(
                "tool",
                "rg",
                "--project",
                self.project,
                "--root",
                "mcu",
                "--pattern",
                "EXTERNAL_DIRECTORY_SECRET",
            )

        self.assertEqual(exit_code, 0, value)
        self.assertEqual(value["match_count"], 0)
        self.assertNotIn(secret, json.dumps(value))

    def test_python_search_does_not_enter_reparse_directory(self) -> None:
        secret = "SIMULATED_JUNCTION_SECRET_9b2e"
        reparse_directory = self.repo / "project" / "simulated-junction"
        reparse_directory.mkdir()
        (reparse_directory / "secret.txt").write_text(secret, encoding="utf-8")
        real_is_reparse_point = embedded_runtime_common.is_reparse_point

        def simulated_reparse(path: Path) -> bool:
            return path.name == reparse_directory.name or real_is_reparse_point(path)

        with (
            mock.patch.object(embedded_runtime_common, "is_reparse_point", side_effect=simulated_reparse),
            mock.patch.object(embedded_runtime_tools, "run_ripgrep", return_value=None),
        ):
            exit_code, value = self.call(
                "tool",
                "rg",
                "--project",
                self.project,
                "--root",
                "mcu",
                "--pattern",
                "SIMULATED_JUNCTION_SECRET",
            )

        self.assertEqual(exit_code, 0, value)
        self.assertEqual(value["match_count"], 0)
        self.assertNotIn(secret, json.dumps(value))

    def test_discovery_does_not_infer_target_from_external_directory_symlink(self) -> None:
        workspace = self.base / "linked-workspace"
        outside_mcu = self.base / "outside-mcu"
        workspace.mkdir()
        outside_mcu.mkdir()
        (outside_mcu / "external.uvprojx").write_text(
            "<Project><Device>EXTERNAL_SECRET</Device></Project>\n",
            encoding="utf-8",
        )
        try:
            (workspace / "mcu").symlink_to(outside_mcu, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        background = embedded_runtime_common.discover_background(
            "linked-project",
            workspace,
        )

        self.assertEqual("unknown", background["architecture"])
        self.assertEqual([], background["build_files"])
        self.assertEqual([], background["toolchains"]["keil_projects"])
        self.assertNotIn("EXTERNAL_SECRET", json.dumps(background))


if __name__ == "__main__":
    unittest.main()
