from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

from embedded_runtime_operations import command_rtt  # noqa: E402


class RttGateTests(unittest.TestCase):
    def invoke(self, *, reset: bool, require_confirm: bool = False, confirm: bool = False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        workspace = root / "workspace"
        workspace.mkdir()
        project_dir = root / "projects" / "sample"
        project_dir.mkdir(parents=True)
        background = {
            "project_id": "sample",
            "background_id": "sample:test",
            "workspace": str(workspace),
            "architecture": "mcu-only",
            "targets": {"mcu": {"path": str(workspace)}},
            "fingerprints": [],
        }
        (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")
        args = argparse.Namespace(
            root=root,
            agentctl=root / "agentctl.py",
            project="sample",
            target="mcu",
            wait_ms=12000,
            reset=reset,
            require_confirm=require_confirm,
            confirm=confirm,
            json=True,
        )
        output = StringIO()
        with patch(
            "embedded_runtime_operations.run_agentctl",
            return_value={"ok": True, "operation": "rtt-capture-mcu", "exit_code": 0},
        ) as backend, redirect_stdout(output):
            exit_code = command_rtt(args)
        return exit_code, json.loads(output.getvalue()), backend

    def test_reset_requires_gate_before_backend(self) -> None:
        exit_code, value, backend = self.invoke(reset=True)
        self.assertEqual(exit_code, 2)
        self.assertEqual(value["state"], "blocked")
        self.assertTrue(value["requires_human_confirm"])
        self.assertEqual(value["gate"]["level"], "L3")
        backend.assert_not_called()

    def test_reset_requires_explicit_confirmation_before_backend(self) -> None:
        exit_code, value, backend = self.invoke(reset=True, require_confirm=True)
        self.assertEqual(exit_code, 3)
        self.assertEqual(value["state"], "approval_required")
        self.assertFalse(value["gate"]["confirmed"])
        backend.assert_not_called()

    def test_attach_remains_read_only_without_confirmation(self) -> None:
        exit_code, value, backend = self.invoke(reset=False)
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["gate"]["level"], "L0")
        self.assertFalse(value["gate"]["requires_human_confirm"])
        backend.assert_called_once()

    def test_confirmed_reset_forwards_defense_in_depth_gate(self) -> None:
        exit_code, value, backend = self.invoke(reset=True, require_confirm=True, confirm=True)
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["gate"]["level"], "L3")
        self.assertTrue(value["gate"]["confirmed"])
        forwarded = backend.call_args.args[1]
        self.assertIn("--reset", forwarded)
        self.assertIn("--require-confirm", forwarded)
        self.assertIn("--confirm", forwarded)


if __name__ == "__main__":
    unittest.main()
