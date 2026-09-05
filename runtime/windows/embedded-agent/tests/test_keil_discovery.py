from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


RUNTIME_DIR = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_common import infer_targets, parse_keil  # noqa: E402
import embedded_runtime_common  # noqa: E402
import embedded_runtime_knowledge  # noqa: E402
from embedded_runtime_knowledge import command_project  # noqa: E402


PROJECT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<Project>
  <Targets><Target><TargetName>{target}</TargetName><TargetOption><TargetCommonOption>
    <Device>AC78428YILA</Device>
    <FlashDriverDll>UL2CM3(-FD1FFE0000 -FC1000 -FN1 -FF0AC7842X_BANK0 -FS00 -FL0100000)</FlashDriverDll>
    <OutputDirectory>.\\Objects\\</OutputDirectory>
    <OutputName>{output}</OutputName>
    <CreateExecutable>{executable}</CreateExecutable>
    <CreateLib>{library}</CreateLib>
  </TargetCommonOption></TargetOption></Target></Targets>
</Project>
"""

OPTIONS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<ProjectOpt><Target><TargetOption><DebugOpt><pMon>Segger\\JL2CM3.dll</pMon></DebugOpt>
<TargetDriverDllRegistry><SetRegEntry><Key>JL2CM3</Key>
<Name>-U69730342 -S2 -ZTIFSpeedSel5000 -N00(&quot;ARM CoreSight SW-DP&quot;) -D00(2BA01477) -FD1FFE0000 -FC1000 -FN1 -FF0AC7842X_BANK0.FLM -FS00 -FL0100000</Name>
</SetRegEntry></TargetDriverDllRegistry></TargetOption></Target></ProjectOpt>
"""


class KeilDiscoveryTests(unittest.TestCase):
    def write_project(self, root: Path, relative: str, *, executable: bool) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            PROJECT_TEMPLATE.format(
                target="application" if executable else "autosar_stack",
                output="application" if executable else "libautosar_stack.lib",
                executable=int(executable),
                library=int(not executable),
            ),
            encoding="utf-8",
        )
        return path

    def test_discovery_requires_explicit_project_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = parse_keil(self.write_project(root, "autosar_stack/autosar.uvprojx", executable=False), root)
            application_path = self.write_project(root, "mcu/project/mdk/application.uvprojx", executable=True)
            application_path.with_suffix(".uvoptx").write_text(OPTIONS_TEMPLATE, encoding="utf-8")
            application = parse_keil(application_path, root)
            unresolved = infer_targets(
                root,
                "mcu-only",
                [{"kind": "keil", "path": library["path"]}, {"kind": "keil", "path": application["path"]}],
                [library, application],
            )
            targets = infer_targets(
                root,
                "mcu-only",
                [{"kind": "keil", "path": library["path"]}, {"kind": "keil", "path": application["path"]}],
                [library, application],
                mcu_keil_project=r"MCU\PROJECT\MDK\APPLICATION.uvprojx",
                selection_source="explicit",
            )

        unresolved_build = unresolved["mcu"]["build"]
        self.assertEqual(unresolved_build["selection_status"], "selection_required")
        self.assertIsNone(unresolved_build["project"])
        self.assertEqual(len(unresolved_build["selection_candidates"]), 2)
        build = targets["mcu"]["build"]
        self.assertEqual(build["selection_status"], "selected")
        self.assertEqual(build["project"], "mcu/project/mdk/application.uvprojx")
        self.assertEqual(build["selection_source"], "explicit")
        self.assertEqual(application["output_kind"], "executable")
        self.assertEqual(application["user_options"]["monitor"], r"Segger\JL2CM3.dll")
        self.assertEqual(application["user_options"]["probe_serial"], "69730342")
        self.assertEqual(application["user_options"]["speed_khz"], 5000)
        self.assertEqual(application["user_options"]["dpidr"], "0x2BA01477")
        self.assertEqual(application["user_options"]["flash_algorithms"][0]["start"], "0x0")

    def test_invalid_or_library_selection_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = parse_keil(self.write_project(root, "mcu/a/firmware.uvprojx", executable=True), root)
            second = parse_keil(self.write_project(root, "mcu/b/firmware.uvprojx", executable=True), root)
            invalid = infer_targets(
                root,
                "mcu-only",
                [{"kind": "keil", "path": first["path"]}, {"kind": "keil", "path": second["path"]}],
                [first, second],
                mcu_keil_project="mcu/missing.uvprojx",
            )
            library = parse_keil(self.write_project(root, "vendor/library.uvprojx", executable=False), root)
            invalid_kind = infer_targets(
                root,
                "mcu-only",
                [{"kind": "keil", "path": library["path"]}],
                [library],
                mcu_keil_project=library["path"],
            )

        self.assertEqual(invalid["mcu"]["build"]["selection_status"], "invalid_selection")
        self.assertIsNone(invalid["mcu"]["build"]["project"])
        self.assertEqual(invalid_kind["mcu"]["build"]["selection_status"], "invalid_kind")

    def test_background_write_requires_selection_and_then_reuses_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            workspace = Path(directory) / "workspace"
            self.write_project(workspace, "firmware/product.uvprojx", executable=True)

            def discover(selected: str | None) -> tuple[int, dict[str, object]]:
                args = argparse.Namespace(
                    root=root,
                    project_action="discover",
                    project="sample",
                    workspace=str(workspace),
                    mcu_keil_project=selected,
                    write_background=True,
                    json=True,
                )
                output = StringIO()
                with (
                    mock.patch.object(
                        embedded_runtime_common,
                        "DEFAULT_WORKSPACE_ROOT",
                        workspace.parent,
                    ),
                    redirect_stdout(output),
                ):
                    exit_code = command_project(args)
                return exit_code, json.loads(output.getvalue())

            blocked_exit, blocked = discover(None)
            selected_exit, selected = discover("firmware/product.uvprojx")
            reused_exit, reused = discover(None)
            background = json.loads((root / "projects" / "sample" / "background.json").read_text(encoding="utf-8"))

        self.assertEqual(blocked_exit, 5)
        self.assertTrue(blocked["requires_user_selection"])
        self.assertEqual(blocked["selection_candidates"][0]["path"], "firmware/product.uvprojx")
        self.assertEqual(selected_exit, 0)
        self.assertEqual(reused_exit, 0)
        self.assertEqual(selected["selection_status"], "selected")
        self.assertEqual(reused["selection_status"], "selected")
        self.assertEqual(background["targets"]["mcu"]["build"]["selection_source"], "existing_background")

    def test_discovery_rejects_workspace_outside_machine_root_before_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            outside = root / "outside"
            allowed.mkdir()
            outside.mkdir()
            args = argparse.Namespace(
                root=root / "runtime",
                project_action="discover",
                project="sample",
                workspace=str(outside),
                mcu_keil_project=None,
                write_background=True,
                json=True,
            )
            output = StringIO()
            with (
                mock.patch.object(
                    embedded_runtime_common,
                    "DEFAULT_WORKSPACE_ROOT",
                    allowed,
                ),
                mock.patch.object(
                    embedded_runtime_knowledge,
                    "discover_background",
                ) as discover,
                redirect_stdout(output),
            ):
                exit_code = command_project(args)

        value = json.loads(output.getvalue())
        self.assertEqual(5, exit_code)
        self.assertTrue(value["blocked"])
        self.assertIn("configured workspace root", value["first_failure"])
        discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
