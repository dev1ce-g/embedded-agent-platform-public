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

from embedded_runtime_operations import command_build  # noqa: E402


class BuildSelectionGateTests(unittest.TestCase):
    def test_keil_build_requires_user_selected_project(self) -> None:
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
