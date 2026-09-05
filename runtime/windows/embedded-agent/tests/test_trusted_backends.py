from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
BIN = RUNTIME.parent / "bin"
sys.path.insert(0, str(RUNTIME))

import embedded_agent
import embedded_runtime_common as runtime_common
import embedded_runtime_sdk as runtime_sdk


class TrustedBackendTests(unittest.TestCase):
    def test_agentctl_execution_ignores_namespace_override(self) -> None:
        attacker = Path("attacker-agentctl.py").resolve()
        args = argparse.Namespace(agentctl=attacker)
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=b'{"ok":true,"exit_code":0}\n',
            stderr=b"",
        )
        with (
            mock.patch.dict(
                os.environ,
                {
                    "EMBEDDED_AGENTCTL": str(attacker),
                    "EMBEDDED_SDK_MANAGER": str(attacker),
                },
            ),
            mock.patch.object(runtime_common.subprocess, "run", return_value=completed) as run,
        ):
            value = runtime_common.run_agentctl(args, ["status"])

        self.assertTrue(value["ok"])
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]), BIN / "agentctl.py")
        self.assertNotIn(str(attacker), command)
        self.assertNotIn("EMBEDDED_AGENTCTL", run.call_args.kwargs["env"])
        self.assertNotIn("EMBEDDED_SDK_MANAGER", run.call_args.kwargs["env"])

    def test_agentctl_validator_rejects_symlink_resource(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            target = root / "attacker.py"
            target.write_text("raise SystemExit(99)\n", encoding="utf-8")
            candidate = bin_dir / "agentctl.py"
            try:
                candidate.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            with (
                mock.patch.object(runtime_common, "RUNTIME_SOURCE_HOME", root),
                mock.patch.object(runtime_common, "DEFAULT_AGENTCTL", candidate),
            ):
                trusted, failure = runtime_common.trusted_agentctl()

        self.assertIsNone(trusted)
        self.assertIn("regular non-symlink", failure or "")

    def test_missing_runtime_sdk_manager_never_uses_namespace_or_environment(self) -> None:
        attacker = Path("attacker-sdk-manager.py").resolve()
        args = argparse.Namespace(
            sdk_action="list",
            sdk_manager=attacker,
            timeout=1,
            max_bytes=1024,
        )
        with (
            mock.patch.dict(os.environ, {"EMBEDDED_SDK_MANAGER": str(attacker)}),
            mock.patch.object(runtime_sdk.subprocess, "run") as run,
        ):
            value = runtime_sdk.run_sdk_manager(args, ["list"])

        self.assertFalse(value["ok"])
        self.assertFalse(value["capability_available"])
        self.assertIn("capability unavailable", value["first_failure"])
        run.assert_not_called()

    def test_public_sdk_override_cannot_select_an_external_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            attacker = root / "sdk_manager.py"
            attacker.write_text(
                "from pathlib import Path\nPath(%r).write_text('executed')\n" % str(marker),
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = embedded_agent.main(
                    ["--sdk-manager", str(attacker), "sdk", "list", "--json"]
                )
            executed = marker.exists()

        self.assertEqual(exit_code, 2)
        value = json.loads(output.getvalue())
        self.assertFalse(value["capability_available"])
        self.assertEqual(Path(value["sdk_manager"]), runtime_common.DEFAULT_SDK_MANAGER)
        self.assertFalse(executed)


if __name__ == "__main__":
    unittest.main()
