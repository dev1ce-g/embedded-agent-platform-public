from __future__ import annotations

import importlib.util
import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_HOME = Path(__file__).resolve().parents[2]
BIN = AGENT_HOME / "bin"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonAdapterTests(unittest.TestCase):
    def run_adapter(self, home: Path, name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["EMBEDDED_AGENT_HOME"] = str(home)
        return subprocess.run(
            [sys.executable, str(BIN / name), *arguments, "-Json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env=environment,
        )

    def test_jlink_flash_gate_closes_before_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_adapter(Path(directory), "flash-mcu-jlink.py")
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 3)
        self.assertTrue(value["requires_human_confirm"])

    def test_jlink_probe_reports_missing_tool_without_running_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_adapter(Path(directory), "jlink-probe.py", "-JLinkPath", str(Path(directory) / "missing.exe"))
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 127)
        self.assertIn("JLink not found", value["first_failure"])

    def test_rtt_jlink_script_supports_native_paths(self) -> None:
        module = load_module("rtt_capture_native_path_test", BIN / "rtt-capture-mcu.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "capture.jlink"
            control_block = root / "工具与自动化" / "rtt-cb.bin"
            module.write_jlink_script(script, "AC78428YILA", 2000, False, "0x20000000", control_block)
            content = script.read_bytes().decode("utf-8")
        self.assertIn(str(control_block), content)

    def test_flash_markers_are_normalized_from_cr_only_log(self) -> None:
        sys.path.insert(0, str(BIN))
        try:
            module = load_module("flash_mcu_marker_test", BIN / "flash-mcu.py")
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "flash.log"
            log.write_bytes(b"Erase Done.\rProgramming Done.\rVerify OK.\rApplication running ...\r")
            erase = module.marker(log, "Erase Done.", (r"Erase Done\.?",))
            programming = module.marker(log, "Programming Done.", (r"Programming Done\.?",))
            verify = module.marker(log, "Verify OK.", (r"Verify OK\.?",))
        self.assertEqual(erase, "Erase Done.")
        self.assertEqual(programming, "Programming Done.")
        self.assertEqual(verify, "Verify OK.")

    def test_keil_flash_requires_exact_discovered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            project = workspace / "mcu" / "project" / "mdk" / "application.uvprojx"
            project.parent.mkdir(parents=True)
            project.write_text("<Project/>", encoding="utf-8")
            unrelated = workspace / "other" / "newer.axf"
            unrelated.parent.mkdir()
            unrelated.write_bytes(b"not-the-selected-artifact")
            uv4 = root / "UV4.exe"
            uv4.write_bytes(b"")
            completed = self.run_adapter(
                root,
                "flash-mcu.py",
                "-Workspace",
                str(workspace),
                "-Project",
                "mcu/project/mdk/application.uvprojx",
                "-Uv4Path",
                str(uv4),
                "-ArtifactName",
                "application",
                "-OutputDirectory",
                ".\\Objects\\",
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 6)
        self.assertIn("Expected flash artifact not found", value["first_failure"])

    def test_adb_url_query_is_redacted(self) -> None:
        sys.path.insert(0, str(BIN))
        try:
            module = load_module("adb_backend_common_test", BIN / "adb_backend_common.py")
        finally:
            sys.path.pop(0)
        safe = module.safe_url("http://example.test/file.ubx?token=secret")
        self.assertNotIn("secret", safe)
        self.assertIn("redacted", safe)

    def test_controlcan_missing_dll_is_inventory_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_adapter(Path(directory), "probe-controlcan.py", "one", "-Dll", str(Path(directory) / "missing.dll"))
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(value["inventory"][0]["exists"])

    def test_zcanpro_probe_returns_failure_for_architecture_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dll = root / "zlgcan.dll"
            content = bytearray(256)
            content[0x3C:0x40] = (128).to_bytes(4, "little")
            opposite_machine = 0x014C if struct.calcsize("P") == 8 else 0x8664
            content[132:134] = opposite_machine.to_bytes(2, "little")
            dll.write_bytes(content)
            completed = self.run_adapter(root, "probe-zcanpro.py", "-Dll", str(dll))

        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(value["ok"])
        self.assertIn("run this adapter", value["first_failure"])

    def test_runtime_bin_contains_no_powershell_adapters_after_migration(self) -> None:
        self.assertEqual(list(BIN.glob("*.ps1")), [])

    def test_claude_prompt_allows_complete_project_ownership(self) -> None:
        sys.path.insert(0, str(BIN))
        try:
            module = load_module("claude_start_test", BIN / "claude-start.py")
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / ".trellis" / "tasks" / "active"
            task.mkdir(parents=True)
            (task / "job-packet.md").write_text("owner: windows\n", encoding="utf-8")
            prompt = module.prompt_text(
                type("Args", (), {"PromptBase64": None, "PromptFile": None, "Prompt": None})(),
                root,
                {"task_dir": task, "task_ref": ".trellis/tasks/active"},
            )
        self.assertIn("requirements, architecture, implementation and verification", prompt)
        self.assertNotIn("Execution Agent", prompt)

    def test_stable_entry_accepts_encoded_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = base64.b64encode(
                json.dumps(
                    {
                        "script": str(BIN / "embedded-agent.py"),
                        "root": directory,
                        "agentctl": str(BIN / "agentctl.py"),
                        "args": ["status", "--json"],
                    }
                ).encode("utf-8")
            ).decode("ascii")
            completed = subprocess.run(
                [sys.executable, str(BIN / "embedded-agent.py"), "--payload-b64", payload],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(value["ok"])
        self.assertEqual(value["runtime_contract_version"], "0.8.0")


if __name__ == "__main__":
    unittest.main()
