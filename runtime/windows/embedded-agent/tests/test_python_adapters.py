from __future__ import annotations

import importlib.util
import base64
import contextlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


AGENT_HOME = Path(__file__).resolve().parents[2]
BIN = AGENT_HOME / "bin"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class PythonAdapterTests(unittest.TestCase):
    def test_backend_artifact_discovery_ignores_external_symlink(self) -> None:
        module = load_module("agent_backend_common_symlink_test", BIN / "agent_backend_common.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            artifacts = root / "artifacts"
            artifacts.mkdir()
            outside = root / "outside.axf"
            outside.write_bytes(b"external")
            try:
                (artifacts / "firmware.axf").symlink_to(outside)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")

            artifact = module.latest_artifact([artifacts], ("*.axf",))

        self.assertIsNone(artifact)

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
            completed = self.run_adapter(Path(directory).resolve(), "flash-mcu-jlink.py")
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 3)
        self.assertTrue(value["requires_human_confirm"])

    def test_mpu_build_rejects_symlinked_embedded_builds_before_docker(self) -> None:
        module = load_module("build_mpu_output_symlink_test", BIN / "build-mpu.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            try:
                (workspace / "_embedded_builds").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            output = io.StringIO()
            with (
                mock.patch.object(module, "new_log_path", return_value=root / "build.log"),
                mock.patch.object(module, "docker_capture") as docker_capture,
                contextlib.redirect_stdout(output),
            ):
                exit_code = module.main(["-Workspace", str(workspace), "-Json"])
            value = json.loads(output.getvalue())

            self.assertEqual(exit_code, 5)
            self.assertFalse(value["ok"])
            self.assertTrue(value["blocked"])
            self.assertEqual(value["schema_version"], "embedded-capability-result/v1")
            self.assertEqual(value["contract_version"], "1.0.0")
            self.assertEqual(value["state"], "blocked")
            self.assertIn("symlink or reparse", value["first_failure"])
            self.assertEqual(list(outside.iterdir()), [])
            docker_capture.assert_not_called()

    def test_mpu_build_rejects_external_artifact_root_before_docker(self) -> None:
        module = load_module("build_mpu_external_output_test", BIN / "build-mpu.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            output = io.StringIO()
            with (
                mock.patch.object(module, "new_log_path", return_value=root / "build.log"),
                mock.patch.object(module, "docker_capture") as docker_capture,
                contextlib.redirect_stdout(output),
            ):
                exit_code = module.main(
                    [
                        "-Workspace",
                        str(workspace),
                        "-ArtifactRoot",
                        str(outside),
                        "-Json",
                    ]
                )
            value = json.loads(output.getvalue())

            self.assertEqual(exit_code, 5)
            self.assertFalse(value["ok"])
            self.assertTrue(value["blocked"])
            self.assertEqual(value["error"]["code"], "POLICY_BLOCKED")
            self.assertIn("artifact root is fixed", value["first_failure"])
            self.assertEqual(list(outside.iterdir()), [])
            docker_capture.assert_not_called()

    def test_mpu_build_rejects_unsafe_existing_container_before_exec(self) -> None:
        module = load_module("build_mpu_container_isolation_test", BIN / "build-mpu.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            base_document = {
                "Id": "builder-id",
                "Config": {"Image": "builder@sha256:" + "a" * 64},
                "State": {"Running": True},
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(workspace),
                        "Destination": "/home/project",
                        "RW": True,
                    }
                ],
                "HostConfig": {
                    "Privileged": False,
                    "NetworkMode": "bridge",
                    "PidMode": "",
                    "IpcMode": "private",
                    "UsernsMode": "",
                    "Devices": [],
                    "DeviceRequests": [],
                    "CapAdd": None,
                },
            }
            cases = (
                (
                    "writable-bind",
                    {"mounts": [{"Type": "bind", "Source": str(root / "outside"), "Destination": "/cache", "RW": True}]},
                    "/home/build/target",
                    "writable mount outside",
                ),
                (
                    "writable-volume",
                    {"mounts": [{"Type": "volume", "Source": "cache", "Destination": "/cache", "RW": True}]},
                    "/home/build/target",
                    "writable mount outside",
                ),
                (
                    "docker-socket-read-only",
                    {"mounts": [{"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": False}]},
                    "/home/build/target",
                    "Docker socket",
                ),
                ("privileged", {"host": {"Privileged": True}}, "/home/build/target", "Privileged"),
                ("host-network", {"host": {"NetworkMode": "host"}}, "/home/build/target", "host network"),
                ("host-pid", {"host": {"PidMode": "host"}}, "/home/build/target", "host PID"),
                ("host-ipc", {"host": {"IpcMode": "host"}}, "/home/build/target", "host IPC"),
                ("host-userns", {"host": {"UsernsMode": "host"}}, "/home/build/target", "host user namespace"),
                ("devices", {"host": {"Devices": [{"PathOnHost": "/dev/kvm"}]}}, "/home/build/target", "device mappings"),
                ("device-requests", {"host": {"DeviceRequests": [{"Capabilities": [["gpu"]]}]}}, "/home/build/target", "device requests"),
                ("cap-add", {"host": {"CapAdd": ["SYS_ADMIN"]}}, "/home/build/target", "added Linux capabilities"),
                (
                    "artifact-equals-mount",
                    {"mounts": [{"Type": "bind", "Source": "/host/output", "Destination": "/home/build/target", "RW": False}]},
                    "/home/build/target",
                    "artifact path overlaps",
                ),
                (
                    "mount-contains-artifact",
                    {"mounts": [{"Type": "bind", "Source": "/host/output", "Destination": "/home/build", "RW": False}]},
                    "/home/build/target",
                    "artifact path overlaps",
                ),
                (
                    "artifact-contains-mount",
                    {"mounts": [{"Type": "bind", "Source": "/host/output", "Destination": "/home/build/target", "RW": False}]},
                    "/home/build",
                    "artifact path overlaps",
                ),
            )

            for name, changes, artifact_path, expected_failure in cases:
                with self.subTest(name=name):
                    document = json.loads(json.dumps(base_document))
                    document["Mounts"].extend(changes.get("mounts", []))
                    document["HostConfig"].update(changes.get("host", {}))
                    docker_calls: list[list[str]] = []

                    def docker_capture(arguments: list[str], timeout: int = 120) -> tuple[int, str]:
                        docker_calls.append(arguments)
                        if arguments == ["container", "inspect", "embedded-build"]:
                            return 0, json.dumps([document])
                        self.fail(f"unsafe container reached Docker operation: {arguments}")

                    output = io.StringIO()
                    with (
                        mock.patch.object(module, "new_log_path", return_value=root / "build.log"),
                        mock.patch.object(module.shutil, "which", return_value="docker"),
                        mock.patch.object(module, "docker_capture", side_effect=docker_capture),
                        mock.patch.object(module, "run_logged") as run_logged,
                        contextlib.redirect_stdout(output),
                    ):
                        exit_code = module.main(
                            [
                                "-Workspace",
                                str(workspace),
                                "-ContainerArtifactPath",
                                artifact_path,
                                "-Json",
                            ]
                        )
                    value = json.loads(output.getvalue())

                    self.assertEqual(exit_code, 5)
                    self.assertFalse(value["ok"])
                    self.assertTrue(value["blocked"])
                    self.assertEqual(value["state"], "blocked")
                    self.assertEqual(value["error"]["code"], "POLICY_BLOCKED")
                    self.assertEqual(value["container_isolation"]["stage"], "requested")
                    self.assertIn(expected_failure, value["first_failure"])
                    self.assertEqual(docker_calls, [["container", "inspect", "embedded-build"]])
                    run_logged.assert_not_called()

    def test_mpu_container_isolation_preserves_read_only_mounts(self) -> None:
        module = load_module("build_mpu_read_only_mount_test", BIN / "build-mpu.py")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve() / "workspace"
            workspace.mkdir()
            document = {
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(workspace),
                        "Destination": "/home/project",
                        "RW": True,
                    },
                    {
                        "Type": "bind",
                        "Source": "/opt/toolchain",
                        "Destination": "/opt/toolchain",
                        "RW": False,
                    },
                ],
                "HostConfig": {
                    "Privileged": False,
                    "NetworkMode": "bridge",
                    "PidMode": "",
                    "IpcMode": "private",
                    "UsernsMode": "",
                    "Devices": [],
                    "CapAdd": None,
                },
            }
            workspace_mount, mount_failure = module.validate_workspace_mount(
                document,
                workspace,
                "/home/project/mpu/project/cmake",
            )
            isolation_failure = module.validate_container_isolation(
                document,
                workspace_mount,
                "/home/build/target",
            )

        self.assertIsNotNone(workspace_mount)
        self.assertIsNone(mount_failure)
        self.assertIsNone(isolation_failure)

    def test_jlink_probe_reports_missing_tool_without_running_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_adapter(Path(directory).resolve(), "jlink-probe.py", "-JLinkPath", str(Path(directory).resolve() / "missing.exe"))
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 127)
        self.assertIn("JLink not found", value["first_failure"])

    def test_jlink_probe_script_rejects_token_injection(self) -> None:
        module = load_module("jlink_probe_injection_test", BIN / "jlink-probe.py")
        with self.assertRaises(ValueError):
            module.probe_commands("S32K312\nexit", "SWD", "1000", False, False)

    def test_rtt_jlink_script_supports_native_paths(self) -> None:
        module = load_module("rtt_capture_native_path_test", BIN / "rtt-capture-mcu.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            script = root / "capture.jlink"
            control_block = root / "工具与自动化" / "rtt-cb.bin"
            control_block.parent.mkdir()
            module.write_jlink_script(script, "AC78428YILA", 2000, False, "0x20000000", control_block)
            content = script.read_bytes().decode("utf-8")
        self.assertIn(f'"{control_block.resolve()}"', content)

    def test_rtt_jlink_script_rejects_device_command_injection(self) -> None:
        module = load_module("rtt_capture_device_injection_test", BIN / "rtt-capture-mcu.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with self.assertRaisesRegex(ValueError, "device"):
                module.write_jlink_script(
                    root / "capture.jlink",
                    "AC78428YILA\nexit",
                    2000,
                    False,
                    "0x20000000",
                    root / "rtt-cb.bin",
                )

    def test_rtt_rejects_malicious_keil_device_before_starting_jlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            mdk = workspace / "mcu" / "project" / "mdk"
            objects = mdk / "Objects"
            objects.mkdir(parents=True)
            (mdk / "application.uvprojx").write_text(
                "<Project><Device>AC78428YILA\nexit</Device>"
                "<OutputName>application</OutputName>"
                "<OutputDirectory>Objects</OutputDirectory></Project>",
                encoding="utf-8",
            )
            (objects / "application.axf").write_bytes(b"axf")
            (objects / "application.map").write_text(
                "_SEGGER_RTT 0x20000000 Data\n",
                encoding="utf-8",
            )
            marker = root / "jlink-started"
            jlink = root / "JLink"
            jlink.write_text(
                f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(marker)!r}).write_text('started')\n",
                encoding="utf-8",
            )
            jlink.chmod(0o755)
            uv4 = root / "UV4.exe"
            fromelf = root / "fromelf.exe"
            uv4.write_bytes(b"tool")
            fromelf.write_bytes(b"tool")

            completed = self.run_adapter(
                root,
                "rtt-capture-mcu.py",
                "-Workspace",
                str(workspace),
                "-Uv4Path",
                str(uv4),
                "-JLinkPath",
                str(jlink),
                "-FromElfPath",
                str(fromelf),
            )
            started = marker.exists()

        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(started)
        self.assertIn("single-line", value["first_failure"])

    def test_jlink_flash_script_rejects_all_interpolated_injections(self) -> None:
        module = load_module("jlink_flash_injection_test", BIN / "flash-mcu-jlink.py")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory).resolve() / "application.bin"
            binary.write_bytes(b"firmware")
            invalid_values = (
                ("S32K312\nexit", "SWD", "1000", "0x00400000", binary),
                ("S32K312", "SWD\nexit", "1000", "0x00400000", binary),
                ("S32K312", "SWD", "1000\nexit", "0x00400000", binary),
                ("S32K312", "SWD", "1000", "0x00400000\nexit", binary),
                ("S32K312", "SWD", "1000", "0x00400000", Path(f"{binary}\nexit")),
            )
            for device, interface, speed, address, path in invalid_values:
                with self.subTest(value=(device, interface, speed, address, path)):
                    with self.assertRaises(ValueError):
                        module.flash_commands(device, interface, speed, address, path, False)

    def test_jlink_flash_script_quotes_binary_path(self) -> None:
        module = load_module("jlink_flash_path_test", BIN / "flash-mcu-jlink.py")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory).resolve() / "固件 image.bin"
            binary.write_bytes(b"firmware")
            commands, normalized = module.flash_commands(
                "S32K312",
                "swd",
                "1000",
                "0x00400000",
                binary,
                False,
            )
        self.assertEqual(normalized["interface"], "SWD")
        self.assertIn(f'loadbin "{binary.resolve()}", 0x00400000', commands)

    def test_flash_markers_are_normalized_from_cr_only_log(self) -> None:
        sys.path.insert(0, str(BIN))
        try:
            module = load_module("flash_mcu_marker_test", BIN / "flash-mcu.py")
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory).resolve() / "flash.log"
            log.write_bytes(b"Erase Done.\rProgramming Done.\rVerify OK.\rApplication running ...\r")
            erase = module.marker(log, "Erase Done.", (r"Erase Done\.?",))
            programming = module.marker(log, "Programming Done.", (r"Programming Done\.?",))
            verify = module.marker(log, "Verify OK.", (r"Verify OK\.?",))
        self.assertEqual(erase, "Erase Done.")
        self.assertEqual(programming, "Programming Done.")
        self.assertEqual(verify, "Verify OK.")

    def test_keil_flash_requires_exact_discovered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
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

    def test_controlcan_probe_rejects_cli_dll_without_machine_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_adapter(Path(directory).resolve(), "probe-controlcan.py", "one", "-Dll", str(Path(directory).resolve() / "missing.dll"))
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(value["ok"])
        self.assertEqual(value["inventory"], [])
        self.assertIn("driver configuration", value["first_failure"])

    def test_zcanpro_probe_rejects_workspace_dll_without_machine_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dll = root / "zlgcan.dll"
            content = bytearray(256)
            content[0x3C:0x40] = (128).to_bytes(4, "little")
            opposite_machine = 0x014C if struct.calcsize("P") == 8 else 0x8664
            content[132:134] = opposite_machine.to_bytes(2, "little")
            dll.write_bytes(content)
            completed = self.run_adapter(root, "probe-zcanpro.py", "-Dll", str(dll))

        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(value["ok"])
        self.assertIn("driver configuration", value["first_failure"])

    def test_runtime_bin_contains_no_powershell_adapters_after_migration(self) -> None:
        self.assertEqual(list(BIN.glob("*.ps1")), [])

    def test_runtime_has_no_model_specific_launcher(self) -> None:
        self.assertFalse((BIN / "claude-start.py").exists())

    def test_runtime_upgrade_removes_retired_model_launcher(self) -> None:
        module = load_module("windows_runtime_install_test", AGENT_HOME / "install.py")
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory).resolve() / "installed-runtime"
            obsolete = prefix / "bin" / "claude-start.py"
            obsolete.parent.mkdir(parents=True)
            obsolete.write_text("legacy launcher\n", encoding="utf-8")
            module.copy_runtime(prefix)
            self.assertFalse(obsolete.exists())

    def test_stable_entry_accepts_encoded_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            machine_install = Path(directory).resolve() / "machine-install"
            payload_root = Path(directory).resolve() / "payload-controlled-state"
            attacker = Path(directory).resolve() / "attacker.py"
            attacker.write_text("raise SystemExit('must not run')\n", encoding="utf-8")
            payload = base64.b64encode(
                json.dumps(
                    {
                        "script": str(attacker),
                        "root": str(payload_root),
                        "agentctl": str(attacker),
                        "args": ["status", "--json"],
                    }
                ).encode("utf-8")
            ).decode("ascii")
            environment = os.environ.copy()
            environment["EMBEDDED_AGENT_INSTALL_ROOT"] = str(machine_install)
            environment["EMBEDDED_AGENT_ROOT"] = str(Path(directory).resolve() / "env-controlled-state")
            environment["EMBEDDED_AGENTCTL"] = str(attacker)
            environment["EMBEDDED_SDK_MANAGER"] = str(attacker)
            completed = subprocess.run(
                [sys.executable, str(BIN / "embedded-agent.py"), "--payload-b64", payload],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=environment,
            )
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(value["ok"])
        self.assertEqual(Path(value["root"]), machine_install / "state")
        self.assertEqual(Path(value["agentctl"]), BIN / "agentctl.py")
        self.assertEqual(value["runtime_contract_version"], "1.0.0")

    def test_stable_entry_rejects_launcher_global_overrides(self) -> None:
        attempts = (
            ["--root", "attacker-state", "status"],
            ["--root=attacker-state", "status"],
            ["--r=attacker-state", "status"],
            ["--agentctl", "attacker.py", "status"],
            ["--agentctl=attacker.py", "status"],
            ["--a=attacker.py", "status"],
            ["--sdk-manager", "attacker.py", "status"],
            ["--sdk-manager=attacker.py", "status"],
            ["--s=attacker.py", "status"],
        )
        for arguments in attempts:
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [sys.executable, str(BIN / "embedded-agent.py"), *arguments],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                value = json.loads(completed.stdout)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(value["schema_version"], "embedded-capability-result/v1")
                self.assertEqual(value["contract_version"], "1.0.0")
                self.assertEqual(value["capability_id"], "agent.launcher")
                self.assertEqual(value["phase"], "execute")
                self.assertEqual(value["state"], "failed")
                self.assertEqual(value["evidence"], [])
                self.assertEqual(value["error"]["code"], "INVALID_REQUEST")
                self.assertIn("cannot be overridden", value["first_failure"])

    def test_stable_entry_allows_command_scoped_git_root(self) -> None:
        module = load_module("stable_embedded_agent_test", BIN / "embedded-agent.py")
        arguments = ["git", "status", "--project", "demo", "--root", "mcu"]
        self.assertIsNone(module.sensitive_global_override(arguments))

    def test_stable_entry_rejects_symlink_backend_resource(self) -> None:
        module = load_module("stable_embedded_agent_symlink_test", BIN / "embedded-agent.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            trusted_dir = root / "bin"
            trusted_dir.mkdir()
            attacker = root / "attacker.py"
            attacker.write_text("raise SystemExit(99)\n", encoding="utf-8")
            candidate = trusted_dir / "agentctl.py"
            try:
                candidate.symlink_to(attacker)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            trusted, failure = module.trusted_python_resource(
                candidate,
                trusted_dir,
                "Agent control backend",
            )
        self.assertIsNone(trusted)
        self.assertIn("regular non-symlink", failure or "")


if __name__ == "__main__":
    unittest.main()
