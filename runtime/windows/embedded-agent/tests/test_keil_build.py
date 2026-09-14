from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import embedded_runtime_operations as operations
from test_python_adapters import BIN, load_module


class KeilLibraryBuildTests(unittest.TestCase):
    def run_build(self, root, *, raw_exit=1, message='0 Error(s), 17 Warning(s).',
                  artifact=True, kind="library", name="firmware"):
        module = load_module("keil_build_output_test", BIN / "build-mcu.py")
        workspace = root / "workspace"
        project = workspace / "vendor" / "library.uvprojx"
        project.parent.mkdir(parents=True)
        project.write_text("<Project/>", encoding="utf-8")
        uv4 = root / "UV4.exe"
        uv4.write_bytes(b"")
        suffix = ".lib" if kind == "library" else ".axf"
        filename = name if name.lower().endswith(suffix) else name + suffix

        def fake_build(command, log, **kwargs):
            self.assertEqual(command[1:6], ["-b", str(project), "-t", "selected-target", "-j0"])
            if artifact:
                output = project.parent / "Objects" / filename
                output.parent.mkdir()
                output.write_bytes(b"compiled-output")
            if message:
                module.write_log(project.parent / "agentctl_mcu_uv4_build.log", message)
            return raw_exit, "", ""

        output = io.StringIO()
        with (mock.patch.object(module, "run_logged", side_effect=fake_build),
              mock.patch.object(module, "new_log_path", return_value=root / "build.log"),
              contextlib.redirect_stdout(output)):
            code = module.main([
                "-Workspace", str(workspace), "-Project", "vendor/library.uvprojx",
                "-Uv4Path", str(uv4), "-Target", "selected-target", "-ArtifactKind", kind,
                "-ArtifactName", name, "-Json",
            ])
        return code, json.loads(output.getvalue())

    def test_accepts_warning_exit_and_reports_library_with_or_without_suffix(self):
        for name, expected in (("firmware", "firmware.lib"), ("firmware.lib", "firmware.lib"),
                               ("firmware.v1", "firmware.v1.lib")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                code, value = self.run_build(Path(directory).resolve(), name=name)
                self.assertEqual(code, 0)
                self.assertTrue(value["ok"])
                self.assertEqual(value["tool_exit_code"], 1)
                self.assertTrue(value["artifact"]["path"].endswith(expected))

    def test_warning_exit_uses_error_summary_even_after_completion_line(self):
        with tempfile.TemporaryDirectory() as directory:
            code, value = self.run_build(Path(directory).resolve(), message="Build complete\n0 Error(s), 2 Warning(s).")
            self.assertEqual(code, 0)
            self.assertTrue(value["ok"])

    def test_rejects_missing_log_artifact_nonzero_errors_and_failed_tool(self):
        for arguments in (
            {"artifact": False}, {"raw_exit": 0, "message": ""},
            {"raw_exit": 0, "message": "Build complete\n10 Error(s), 0 Warning(s)."},
            {"raw_exit": 0, "message": "0 Error(s)\nPost-build failed"},
            {"raw_exit": 2}, {"raw_exit": 1, "message": "Build complete"},
        ):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                code, value = self.run_build(Path(directory).resolve(), **arguments)
                self.assertNotEqual(code, 0)
                self.assertFalse(value["ok"])
                self.assertTrue(value["first_failure"])

    def test_executable_build_keeps_axf_output(self):
        with tempfile.TemporaryDirectory() as directory:
            code, value = self.run_build(Path(directory).resolve(), kind="executable", raw_exit=0)
            self.assertEqual(code, 0)
            self.assertTrue(value["artifact"]["path"].endswith("firmware.axf"))

    def test_runtime_forwards_library_kind_from_new_and_old_backgrounds(self):
        for persisted_kind in (True, False):
            with self.subTest(persisted_kind=persisted_kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                workspace = root / "workspace"
                workspace.mkdir()
                build = {"method": "keil", "project": "vendor/library.uvprojx", "target": "library",
                         "output": "firmware", "selection_status": "selected", "selection_source": "explicit"}
                if persisted_kind:
                    build["output_kind"] = "library"
                background = {"project_id": "sample", "background_id": "sample:test",
                              "workspace": str(workspace), "targets": {"mcu": {"build": build}},
                              "toolchains": {"keil_projects": [{"path": build["project"], "output_kind": "library"}]},
                              "fingerprints": [], "capabilities": {"flash": {"status": "gated", "requires_human_confirm": True}}}
                project_dir = root / "projects" / "sample"
                project_dir.mkdir(parents=True)
                (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")
                args = argparse.Namespace(root=root, project="sample", target="keil", sdk_path=None,
                                          dry_run=False, json=True, require_confirm=True, confirm=True)
                with (mock.patch.object(operations, "run_agentctl", return_value={"ok": True, "exit_code": 0}) as backend,
                      contextlib.redirect_stdout(io.StringIO())):
                    self.assertEqual(operations.command_build(args), 0)
                command = backend.call_args.args[1]
                self.assertEqual(command[command.index("--artifact-kind") + 1], "library")
                args.target = "mcu"
                output = io.StringIO()
                with (mock.patch.object(operations, "run_agentctl") as backend,
                      contextlib.redirect_stdout(output)):
                    self.assertEqual(operations.command_flash(args), 5)
                self.assertEqual(json.loads(output.getvalue())["gate"], "mcu-keil-output-kind")
                backend.assert_not_called()

    def test_dispatcher_forwards_artifact_kind_without_changing_target(self):
        dispatcher = load_module("keil_dispatcher_test", BIN / "agentctl.py")
        with mock.patch.object(dispatcher, "run_adapter", return_value=0) as adapter:
            code = dispatcher.main(["build", "mcu", "--workspace", "workspace",
                                    "--project-path", "vendor/library.uvprojx", "--keil-target", "library",
                                    "--artifact-kind", "library", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(adapter.call_args.args, (
            "build-mcu.py", ["-Workspace", "workspace", "-Project", "vendor/library.uvprojx",
                             "-Target", "library", "-ArtifactKind", "library"], True,
        ))


if __name__ == "__main__":
    unittest.main()
