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
import embedded_runtime_sdk


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
        with (
            mock.patch.object(embedded_runtime_sdk, "DEFAULT_SDK_STORE", self.sdk_store),
            mock.patch.object(embedded_runtime_sdk, "DEFAULT_SDK_LOCK", self.sdk_lock),
            contextlib.redirect_stdout(output),
        ):
            exit_code = embedded_agent.main(["--root", str(self.root), *arguments, "--json"])
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

    def test_materialize_rejects_reparse_ancestor_before_write(self) -> None:
        external = self.base / "external"
        external.mkdir()
        linked_parent = self.workspace / "mcu" / "vendor"
        linked_parent.symlink_to(external, target_is_directory=True)

        for mode in ("copy", "junction"):
            arguments = self.mapping_args("materialize", "--confirm")
            arguments[arguments.index("mcu/sdk")] = "mcu/vendor/sdk"
            arguments[arguments.index("junction")] = mode
            with (
                self.subTest(mode=mode),
                mock.patch.object(embedded_runtime_sdk.shutil, "copytree") as copytree,
                mock.patch.object(embedded_runtime_sdk.subprocess, "run") as run,
            ):
                exit_code, value = self.call(*arguments)
                self.assertEqual(exit_code, 5)
                self.assertEqual(value["unsafe_ancestor"], str(linked_parent))
                self.assertEqual(
                    value["first_failure"],
                    "Path must not traverse a symlink or reparse point",
                )
                self.assertFalse((external / "sdk").exists())
                copytree.assert_not_called()
                run.assert_not_called()

    def test_public_sdk_commands_reject_caller_selected_roots(self) -> None:
        parser = embedded_agent.build_parser()
        for arguments in (
            ["sdk", "components", "--sdk", self.sdk, "--sdk-store", str(self.base)],
            ["sdk", "project-resolve", "--project", self.project, "--workspace", str(self.base)],
            [*self.mapping_args("check-mapping"), "--sdk-lock", str(self.base / "forged.lock")],
        ):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(arguments)


if __name__ == "__main__":
    unittest.main()
