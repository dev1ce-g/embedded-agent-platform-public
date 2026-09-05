from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent


class GitSwitchTests(unittest.TestCase):
    project = "test-project"
    branch = "sample.dev-runtime-switch-20260830"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.root = self.base / "agent"
        self.workspace = self.base / "workspace"
        self.repo = self.workspace / "mcu"
        self.remote = self.base / "remote.git"
        self.seed = self.base / "seed"

        self.git(self.base, "init", "--bare", str(self.remote))
        self.git(self.base, "init", str(self.seed))
        self.git(self.seed, "config", "user.email", "agent@example.test")
        self.git(self.seed, "config", "user.name", "Embedded Agent Test")
        (self.seed / "demo.c").write_text("int value = 1;\n", encoding="utf-8")
        self.git(self.seed, "add", "demo.c")
        self.git(self.seed, "commit", "-m", "baseline")
        # Windows build hosts may carry Git versions older than `git switch`.
        self.git(self.seed, "checkout", "-b", self.branch)
        self.git(self.seed, "remote", "add", "origin", str(self.remote))
        self.git(self.seed, "push", "-u", "origin", self.branch)
        self.commit = self.git_output(self.seed, "rev-parse", "HEAD")

        self.workspace.mkdir()
        self.git(self.workspace, "clone", str(self.remote), "mcu")
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

    def call(self, *extra: str) -> tuple[int, dict]:
        output = io.StringIO()
        arguments = [
            "--root", str(self.root), "git", "switch", "--project", self.project,
            "--path", "mcu", "--branch", self.branch, "--commit", self.commit,
            *extra, "--json",
        ]
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(arguments)
        return exit_code, json.loads(output.getvalue())

    def test_switch_attaches_detached_head_to_exact_remote_branch(self) -> None:
        exit_code, value = self.call("--confirm")

        self.assertEqual(exit_code, 0)
        self.assertTrue(value["verified"])
        self.assertEqual(value["after_branch"], self.branch)
        self.assertEqual(value["after"], self.commit)
        self.assertEqual(value["upstream"], f"origin/{self.branch}")
        self.assertTrue(value["created_local_branch"])

    def test_switch_requires_confirmation(self) -> None:
        exit_code, value = self.call()

        self.assertEqual(exit_code, 3)
        self.assertTrue(value["requires_human_confirm"])
        self.assertEqual(self.git_output(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")

    def test_switch_rejects_dirty_workspace(self) -> None:
        (self.repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        exit_code, value = self.call("--confirm")

        self.assertEqual(exit_code, 4)
        self.assertTrue(value["dirty"])

    def test_switch_rejects_remote_sha_mismatch(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main([
                "--root", str(self.root), "git", "switch", "--project", self.project,
                "--path", "mcu", "--branch", self.branch, "--commit", "0" * 40,
                "--confirm", "--json",
            ])
        value = json.loads(output.getvalue())

        self.assertEqual(exit_code, 6)
        self.assertFalse(value["verified"])
        self.assertEqual(value["remote_head"], self.commit)

    def test_status_reports_runtime_contract_and_file_hashes(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(["--root", str(self.root), "status", "--json"])
        value = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            value["platform_version"],
            (Path(__file__).resolve().parents[4] / "VERSION").read_text(encoding="utf-8").strip(),
        )
        self.assertEqual(value["runtime_contract_version"], embedded_agent.RUNTIME_CONTRACT_VERSION)
        self.assertEqual(value["supported_contract_versions"], ["1.0.0"])
        self.assertEqual(value["result_schema_version"], "embedded-capability-result/v1")
        agent_file = next(item for item in value["runtime_files"] if item["path"].endswith("embedded_agent.py"))
        self.assertTrue(agent_file["exists"])
        self.assertEqual(len(agent_file["sha256"]), 64)
        modules = [item for item in value["runtime_files"] if "embedded_runtime_" in item["path"]]
        self.assertEqual(len(modules), len(embedded_agent.RUNTIME_MODULE_FILES))
        self.assertTrue(all(item["exists"] and len(item["sha256"]) == 64 for item in modules))


if __name__ == "__main__":
    unittest.main()
