from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_operations import command_flash  # noqa: E402


class FlashGateTests(unittest.TestCase):
    def test_flash_reaches_confirmation_gate_without_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "projects" / "sample"
            workspace = root / "workspace"
            project_dir.mkdir(parents=True)
            workspace.mkdir()
            background = {
                "project_id": "sample",
                "background_id": "sample:test",
                "workspace": str(workspace),
                "architecture": "mcu-mpu",
                "targets": {"mpu": {"path": str(workspace / "mpu")}},
                "capabilities": {"flash": {"status": "gated", "requires_human_confirm": True}},
                "fingerprints": [],
            }
            (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")
            args = argparse.Namespace(
                root=root,
                project="sample",
                target="mpu",
                require_confirm=False,
                confirm=False,
                json=True,
            )
            output = StringIO()
            with redirect_stdout(output):
                exit_code = command_flash(args)
        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertTrue(value["requires_human_confirm"])
        self.assertNotIn("backend", value)

    def test_flash_requires_confirmation_for_legacy_automatic_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
                        "path": str(workspace / "mcu"),
                        "build": {
                            "method": "keil",
                            "project": "mcu/a.uvprojx",
                            "selection_status": "selected",
                            "selection_candidates": ["mcu/a.uvprojx", "mcu/b.uvprojx"],
                        },
                    }
                },
                "capabilities": {"flash": {"status": "gated", "requires_human_confirm": True}},
                "fingerprints": [],
            }
            (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")
            args = argparse.Namespace(
                root=root,
                project="sample",
                target="mcu",
                require_confirm=True,
                confirm=True,
                json=True,
            )
            output = StringIO()
            with redirect_stdout(output):
                exit_code = command_flash(args)
        value = json.loads(output.getvalue())
        self.assertEqual(exit_code, 5)
        self.assertTrue(value["blocked"])
        self.assertEqual(value["gate"], "mcu-keil-project-selection")
        self.assertEqual(value["selection_status"], "confirmation_required")
        self.assertNotIn("backend", value)


if __name__ == "__main__":
    unittest.main()
