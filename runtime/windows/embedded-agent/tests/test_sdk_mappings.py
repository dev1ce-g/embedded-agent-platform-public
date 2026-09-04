from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent


class SdkMappingTests(unittest.TestCase):
    project = "test-project"
    sdk = "test_sdk"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.root = self.base / "agent"
        self.workspace = self.base / "workspace"
        (self.workspace / "mcu").mkdir(parents=True)
        project_dir = self.root / "projects" / self.project
        project_dir.mkdir(parents=True)
        (project_dir / "background.json").write_text(
            json.dumps(
                {
                    "project_id": self.project,
                    "background_id": "bg-1",
                    "workspace": str(self.workspace),
                    "targets": {"mcu": {"path": str(self.workspace / "mcu")}},
                }
            ),
            encoding="utf-8",
        )

        self.sdk_store = self.base / "sdk"
        self.sdk_manager = self.base / "sdk_manager.py"
        self.sdk_manager.write_text("# test stub\n", encoding="utf-8")
        self.version = self.sdk_store / "versions" / "test_sdk-1.0.0"
        self.source = self.version / "sdk" / "ac78428"
        self.source.mkdir(parents=True)
        current = self.sdk_store / "current"
        current.mkdir(parents=True)
        (current / self.sdk).symlink_to(self.version, target_is_directory=True)
        self.sdk_lock = self.sdk_store / "sdk.lock"
        self.sdk_lock.write_text(
            json.dumps(
                {
                    "packages": {
                        self.sdk: {
                            "version": "1.0.0",
                            "sha256": "a" * 64,
                            "installed_path": str(self.version),
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        self.target = self.workspace / "mcu" / "sdk"
        self.target.symlink_to(self.source, target_is_directory=True)

    def call(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(
                ["--root", str(self.root), "--sdk-manager", str(self.sdk_manager), *arguments, "--json"]
            )
        return exit_code, json.loads(output.getvalue())

    def mapping_args(self, action: str, *extra: str) -> list[str]:
        return [
            "sdk",
            action,
            "--project",
            self.project,
            "--sdk",
            self.sdk,
            "--component",
            "sdk/ac78428",
            "--to",
            "mcu/sdk",
            "--mode",
            "junction",
            "--sdk-store",
            str(self.sdk_store),
            "--sdk-lock",
            str(self.sdk_lock),
            *extra,
        ]

    def test_sdk_mapping_keeps_logical_junction_target_inside_workspace(self) -> None:
        tool_info = embedded_agent.resolve_tool_path({"workspace": str(self.workspace)}, "mcu/sdk")
        sdk_info = embedded_agent.resolve_sdk_target(self.workspace, "mcu/sdk")
        self.assertFalse(tool_info["inside_workspace"])
        self.assertTrue(sdk_info["inside_workspace"])
        self.assertEqual(sdk_info["project_path"], "mcu/sdk")
        self.assertEqual(sdk_info["path"], self.target)

        exit_code, imported = self.call(*self.mapping_args("materialize", "--confirm"))
        self.assertEqual(exit_code, 0)
        self.assertTrue(imported["already_ready"])
        self.assertTrue(imported["mapping_recorded"])
        self.assertTrue(imported["verified"])

        exit_code, checked = self.call(*self.mapping_args("check-mapping"))
        self.assertEqual(exit_code, 0)
        self.assertTrue(checked["valid"])
        self.assertEqual(checked["target"], "mcu/sdk")

        exit_code, build = self.call(
            "build",
            "--project",
            self.project,
            "--target",
            "mcu",
            "--sdk-path",
            "mcu/sdk",
            "--dry-run",
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(build["ok"])
        self.assertEqual(build["sdk_mapping"]["target"], "mcu/sdk")

    def test_copy_mode_does_not_adopt_a_junction(self) -> None:
        exit_code, value = self.call(*self.mapping_args("materialize", "--mode", "copy", "--confirm"))
        self.assertEqual(exit_code, 4)
        self.assertEqual(value["first_failure"], "SDK target already exists and is not an empty directory")


if __name__ == "__main__":
    unittest.main()
