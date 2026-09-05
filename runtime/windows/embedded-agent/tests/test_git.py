from __future__ import annotations

import sys
import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_cli import build_parser  # noqa: E402
import embedded_runtime_common  # noqa: E402
import embedded_runtime_git  # noqa: E402
from embedded_runtime_git import git_clone, valid_clone_branch  # noqa: E402


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

    def test_clone_rejects_workspace_outside_machine_root_before_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            outside = root / "outside"
            allowed.mkdir()
            output = io.StringIO()
            args = argparse.Namespace(
                workspace=str(outside),
                path="repo",
                url="https://example.test/repo.git",
                commit="0" * 40,
                branch=None,
                confirm=True,
                timeout=30,
                max_bytes=4096,
                json=True,
            )
            with (
                mock.patch.object(
                    embedded_runtime_common,
                    "DEFAULT_WORKSPACE_ROOT",
                    allowed,
                ),
                mock.patch.object(embedded_runtime_git.subprocess, "run") as run,
                contextlib.redirect_stdout(output),
            ):
                exit_code = git_clone(args)

        value = json.loads(output.getvalue())
        self.assertEqual(5, exit_code)
        self.assertTrue(value["blocked"])
        self.assertIn("configured workspace root", value["first_failure"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
