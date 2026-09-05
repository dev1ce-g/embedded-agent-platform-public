from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent
import embedded_runtime_sdk


class GitCreateBranchCommitTests(unittest.TestCase):
    project = "test-project"
    branch = "sample.dev-eol-io-20260830"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.root = self.base / "agent"
        self.workspace = self.base / "workspace"
        self.repo = self.workspace / "mcu"
        self.git(self.base, "init", str(self.repo))
        self.git(self.repo, "config", "user.email", "agent@example.test")
        self.git(self.repo, "config", "user.name", "Embedded Agent Test")
        (self.repo / "tracked.c").write_text("int value = 1;\n", encoding="utf-8")
        self.git(self.repo, "add", "tracked.c")
        self.git(self.repo, "commit", "-m", "initial")
        self.commit = self.git_output(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "checkout", "--detach", self.commit)
        project_dir = self.root / "projects" / self.project
        project_dir.mkdir(parents=True)
        (project_dir / "background.json").write_text(
            json.dumps({"project_id": self.project, "background_id": "bg-1", "workspace": str(self.workspace)}),
            encoding="utf-8",
        )

    def git(self, cwd: Path, *arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def git_output(self, cwd: Path, *arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()

    def call(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(["--root", str(self.root), *arguments, "--json"])
        return exit_code, json.loads(output.getvalue())

    def create_branch(self, *extra: str) -> tuple[int, dict]:
        return self.call("git", "create-branch", "--project", self.project, "--path", "mcu", "--branch", self.branch, "--commit", self.commit, *extra)

    def test_create_branch_preserves_dirty_worktree(self) -> None:
        (self.repo / "tracked.c").write_text("int value = 2;\n", encoding="utf-8")
        (self.repo / "new.c").write_text("int added = 1;\n", encoding="utf-8")
        before = self.git_output(self.repo, "status", "--porcelain=v1")

        exit_code, value = self.create_branch("--confirm")

        self.assertEqual(exit_code, 0)
        self.assertTrue(value["worktree_preserved"])
        self.assertTrue(value["dirty"])
        self.assertEqual(self.git_output(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), self.branch)
        self.assertEqual(self.git_output(self.repo, "status", "--porcelain=v1"), before)

    def test_create_branch_requires_exact_current_sha(self) -> None:
        exit_code, value = self.call("git", "create-branch", "--project", self.project, "--path", "mcu", "--branch", self.branch, "--commit", "0" * 40, "--confirm")

        self.assertEqual(exit_code, 6)
        self.assertFalse(value["verified"])

    def test_commit_stages_only_explicit_paths(self) -> None:
        self.assertEqual(self.create_branch("--confirm")[0], 0)
        (self.repo / "tracked.c").write_text("int value = 2;\n", encoding="utf-8")
        (self.repo / "included.c").write_text("int included = 1;\n", encoding="utf-8")
        (self.repo / "excluded.c").write_text("int excluded = 1;\n", encoding="utf-8")

        exit_code, value = self.call(
            "git", "commit", "--project", self.project, "--path", "mcu",
            "--branch", self.branch, "--message", "feat: include selected files",
            "--include", "tracked.c", "--include", "included.c", "--confirm",
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(value["verified"])
        self.assertEqual(set(value["staged_paths"]), {"included.c", "tracked.c"})
        self.assertIn("?? excluded.c", self.git_output(self.repo, "status", "--porcelain=v1"))

    def test_commit_refuses_pre_staged_changes(self) -> None:
        self.assertEqual(self.create_branch("--confirm")[0], 0)
        (self.repo / "tracked.c").write_text("int value = 2;\n", encoding="utf-8")
        self.git(self.repo, "add", "tracked.c")

        exit_code, value = self.call(
            "git", "commit", "--project", self.project, "--path", "mcu",
            "--branch", self.branch, "--message", "feat: should fail",
            "--include", "tracked.c", "--confirm",
        )

        self.assertEqual(exit_code, 4)
        self.assertEqual(value["staged_before"], ["tracked.c"])

    def test_sdk_project_pull_forwards_explicit_name_and_version(self) -> None:
        backend = {
            "ok": True,
            "exit_code": 0,
            "stdout": "downloaded",
            "stderr": "",
            "stdout_bytes": 10,
            "stderr_bytes": 0,
            "truncated": False,
            "first_failure": None,
        }
        trusted_manager = self.base / "runtime-sdk-manager.py"
        trusted_manager.write_text("# test-only internal dependency\n", encoding="utf-8")
        with (
            patch.object(
                embedded_runtime_sdk,
                "trusted_sdk_manager",
                return_value=(trusted_manager, None),
            ),
            patch.object(embedded_runtime_sdk, "run_sdk_manager", return_value=backend) as manager,
        ):
            exit_code, value = self.call(
                "sdk", "project-pull", "--project", self.project,
                "--sdk-name", "hqa802", "--sdk-version", "r09v03", "--confirm",
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(value["ok"])
        self.assertEqual(manager.call_args.args[1], ["project-sdk", "--sdk-name", "hqa802", "--sdk-version", "r09v03"])


if __name__ == "__main__":
    unittest.main()
