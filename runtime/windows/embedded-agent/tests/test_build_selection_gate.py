from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

import embedded_runtime_operations as runtime_operations  # noqa: E402
from embedded_runtime_operations import command_build  # noqa: E402


class BuildSelectionGateTests(unittest.TestCase):
    def test_build_rejects_stale_background_before_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project_dir = root / "projects" / "sample"
            workspace = root / "workspace"
            project_dir.mkdir(parents=True)
            workspace.mkdir()
            background = {
                "project_id": "sample",
                "background_id": "sample:old",
                "workspace": str(workspace),
                "targets": {"mpu": {"build": {"method": "docker"}}},
                "fingerprints": [],
            }
            (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")
            args = argparse.Namespace(
                root=root,
                project="sample",
                target="mpu",
                sdk_path=None,
                dry_run=False,
                json=True,
            )
            output = StringIO()
            stale = {"stale": True, "changed": ["build.ps1"], "missing": []}
            with (
                mock.patch.object(runtime_operations, "compare_background_fingerprints", return_value=stale),
                mock.patch.object(runtime_operations, "run_agentctl") as backend,
                redirect_stdout(output),
            ):
                exit_code = command_build(args)

        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 6)
        self.assertTrue(value["blocked"])
        self.assertEqual(value["background_id"], "sample:old")
        self.assertEqual(value["stale"], stale)
        self.assertEqual(value["first_failure"], "Project background is stale")
        backend.assert_not_called()

    def test_keil_build_requires_user_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project_dir = root / "projects" / "sample"
            workspace = root / "workspace"
            project_dir.mkdir(parents=True)
            workspace.mkdir()
            background = {
                "project_id": "sample",
                "background_id": "sample:test",
                "workspace": str(workspace),
                "architecture": "mcu-only",
                "targets": {
                    "mcu": {
                        "path": str(workspace),
                        "build": {
                            "method": "keil",
                            "project": None,
                            "selection_status": "selection_required",
                            "selection_candidates": ["vendor/a.uvprojx", "firmware/b.uvprojx"],
                        },
                    }
                },
                "fingerprints": [],
            }
            (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")
            args = argparse.Namespace(
                root=root,
                project="sample",
                target="keil",
                sdk_path=None,
                dry_run=True,
                json=True,
            )
            output = StringIO()
            with redirect_stdout(output):
                exit_code = command_build(args)

        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 5)
        self.assertTrue(value["requires_user_selection"])
        self.assertEqual(value["gate"], "keil-project-selection")
        self.assertNotIn("backend", value)


if __name__ == "__main__":
    unittest.main()
