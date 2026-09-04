from __future__ import annotations

import sys
import unittest
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_cli import build_parser  # noqa: E402
from embedded_runtime_git import valid_clone_branch  # noqa: E402


class GitCloneRevisionTests(unittest.TestCase):
    def test_clone_accepts_branch_without_commit(self) -> None:
        args = build_parser().parse_args(
            [
                "git",
                "clone",
                "--project",
                "demo",
                "--workspace",
                r"D:\workspace",
                "--url",
                "git@example.com:group/repo.git",
                "--path",
                "repo",
                "--branch",
                "feature/demo",
            ]
        )
        self.assertEqual(args.branch, "feature/demo")
        self.assertIsNone(args.commit)

    def test_clone_revision_is_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "git",
                    "clone",
                    "--project",
                    "demo",
                    "--workspace",
                    r"D:\workspace",
                    "--url",
                    "git@example.com:group/repo.git",
                    "--path",
                    "repo",
                    "--branch",
                    "feature/demo",
                    "--commit",
                    "0" * 40,
                ]
            )

    def test_branch_validation_rejects_option_and_invalid_ref(self) -> None:
        self.assertTrue(valid_clone_branch("dev_demo-product_baseline_dev"))
        self.assertFalse(valid_clone_branch("-bad"))
        self.assertFalse(valid_clone_branch("bad..branch"))


if __name__ == "__main__":
    unittest.main()
