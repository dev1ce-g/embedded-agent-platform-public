from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "trellis_branch.py"
SPEC = importlib.util.spec_from_file_location("trellis_branch", SCRIPT)
branch = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["trellis_branch"] = branch
SPEC.loader.exec_module(branch)


class BranchFormatTests(unittest.TestCase):
    def test_formats_canonical_component_branch(self):
        value = branch.build_branch("sample.dev", "production-test", "soc", "20260718")
        self.assertTrue(value["ok"])
        self.assertEqual(value["branch"], "sample.dev-production-test-soc-20260718")

    def test_rejects_change_type_as_developer(self):
        value = branch.build_branch("feat", "demo-mcu-xcu", None, "20260718")
        self.assertFalse(value["ok"])

    def test_rejects_slash_style_task_branch(self):
        value = branch.validate_branch("feat/demo-mcu-xcu")
        self.assertFalse(value["ok"])

    def test_accepts_protected_baseline(self):
        value = branch.validate_branch("baseline_dev", allow_protected=True)
        self.assertTrue(value["ok"])
        self.assertEqual(value["kind"], "protected")

    def test_rejects_protected_baseline_for_task_writes(self):
        value = branch.validate_branch("baseline_dev")
        self.assertFalse(value["ok"])

    def test_rejects_invalid_calendar_date(self):
        value = branch.validate_branch("sample.dev-task-20260230")
        self.assertFalse(value["ok"])

    def test_json_flag_is_accepted_after_subcommand_arguments(self):
        args = branch.parse_args([
            "check",
            "--branch", "sample.dev-task-20260718",
            "--json",
        ])
        self.assertTrue(args.json)


class BranchCreateTests(unittest.TestCase):
    def test_creates_canonical_branch_without_upstream(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "README.md").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/legacy-task", "HEAD"],
                check=True,
            )
            args = branch.parse_args([
                "create",
                "--repo", str(repo),
                "--developer", "sample.dev",
                "--task", "uds-provider-bridge",
                "--component", "mcu",
                "--date", "20260718",
                "--base", "origin/legacy-task",
            ])
            self.assertEqual(branch.command_create(args), 0)
            current = subprocess.run(
                ["git", "-C", str(repo), "branch", "--show-current"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            self.assertEqual(current, "sample.dev-uds-provider-bridge-mcu-20260718")
            upstream = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "@{upstream}"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertNotEqual(upstream.returncode, 0)

    def test_refuses_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            args = branch.parse_args([
                "create",
                "--repo", str(repo),
                "--developer", "sample.dev",
                "--task", "task",
                "--date", "20260718",
                "--base", "HEAD",
            ])
            self.assertEqual(branch.command_create(args), 4)


if __name__ == "__main__":
    unittest.main()
