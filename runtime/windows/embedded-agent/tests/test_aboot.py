from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

import embedded_runtime_aboot  # noqa: E402
import embedded_runtime_common  # noqa: E402
from embedded_runtime_aboot import load_aboot_connection, normalize_ports, normalize_windows_exit_code, prepare_aboot_flash, run_aboot_flash, stage_aboot_package  # noqa: E402
from embedded_runtime_cli import build_parser  # noqa: E402


class AbootPreflightTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = root / "workspace"
        package = workspace / "_codex_builds" / "release.zip"
        aboot_root = root / "aboot"
        package.parent.mkdir(parents=True)
        aboot_root.mkdir()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("manifest.txt", "test")
        (aboot_root / "adownload.exe").write_bytes(b"test executable")
        return workspace, package, aboot_root

    def write_registry(
        self,
        root: Path,
        aboot_root: Path,
        *,
        firmware_root: Path | None = None,
        digest: str | None = None,
    ) -> Path:
        firmware_root = firmware_root or root / "firmware"
        firmware_root.mkdir(parents=True, exist_ok=True)
        downloader = aboot_root / "adownload.exe"
        value = {
            "schema_version": embedded_runtime_aboot.ABOOT_CONNECTIONS_SCHEMA,
            "connections": {
                "lab-mpu": {
                    "adownload": str(downloader),
                    "adownload_sha256": digest or hashlib.sha256(downloader.read_bytes()).hexdigest(),
                    "firmware_root": str(firmware_root),
                }
            },
        }
        path = root / "aboot-connections.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def connection(self, root: Path, aboot_root: Path):
        registry = self.write_registry(root, aboot_root)
        with mock.patch.object(embedded_runtime_aboot, "ABOOT_CONNECTIONS_PATH", registry):
            return load_aboot_connection("lab-mpu")

    def test_builds_bounded_usb_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, aboot_root = self.make_fixture(root)
            value = prepare_aboot_flash(
                workspace=workspace,
                package=package,
                connection=self.connection(root, aboot_root),
                ports=[],
                usb_only=True,
                auto_enable=True,
                speed=115200,
                reboot=True,
                at_fallback=False,
            )
        self.assertTrue(value["ok"])
        self.assertEqual(value["command"][1:], ["-q", "-u", "-a", "-s", "115200", "-r", str(package.resolve())])
        self.assertEqual(len(value["package"]["sha256"]), 64)

    def test_rejects_package_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, _, aboot_root = self.make_fixture(root)
            package = root / "external.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("manifest.txt", "test")
            value = prepare_aboot_flash(
                workspace=workspace,
                package=package,
                connection=self.connection(root, aboot_root),
                ports=["COM3"],
                usb_only=False,
                auto_enable=False,
                speed=115200,
                reboot=False,
                at_fallback=False,
            )
        self.assertFalse(value["ok"])
        self.assertTrue(value["blocked"])
        self.assertIn("workspace", value["first_failure"])

    def test_requires_scoped_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, aboot_root = self.make_fixture(root)
            value = prepare_aboot_flash(
                workspace=workspace,
                package=package,
                connection=self.connection(root, aboot_root),
                ports=[],
                usb_only=False,
                auto_enable=False,
                speed=115200,
                reboot=False,
                at_fallback=False,
            )
        self.assertFalse(value["ok"])
        self.assertIn("--usb-only", value["first_failure"])

    def test_normalizes_and_validates_ports(self) -> None:
        ports, failure = normalize_ports(["com3, COM4", "COM3"])
        self.assertIsNone(failure)
        self.assertEqual(ports, ["COM3", "COM4"])
        self.assertIsNotNone(normalize_ports(["ttyUSB0"])[1])

    def test_normalizes_unsigned_windows_exit_code(self) -> None:
        self.assertEqual(normalize_windows_exit_code(4294967295), -1)
        self.assertEqual(normalize_windows_exit_code(0), 0)

    def test_runtime_parser_accepts_mpu_aboot_options(self) -> None:
        args = build_parser().parse_args(
            [
                "flash",
                "--project",
                "demo_project",
                "--target",
                "mpu",
                "--package",
                "release.zip",
                "--connection-id",
                "lab-mpu",
                "--port",
                "COM3",
                "--require-confirm",
                "--confirm",
            ]
        )
        self.assertEqual(args.target, "mpu")
        self.assertEqual(args.port, ["COM3"])
        self.assertEqual(args.package, Path("release.zip"))
        self.assertEqual(args.connection_id, "lab-mpu")

    def test_resolves_relative_package_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, _ = self.make_fixture(root)
            value = stage_aboot_package(workspace, package.relative_to(workspace), root / "firmware")
        self.assertTrue(value["ok"])
        self.assertEqual(Path(value["package_path"]), package.resolve())

    def test_workspace_executable_override_is_rejected_before_subprocess(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            malicious_root = Path(directory) / "workspace" / "tools" / "aboot"
            malicious_root.mkdir(parents=True)
            (malicious_root / "adownload.exe").write_bytes(b"malicious executable")
            arguments = [
                "flash",
                "--project",
                "demo_project",
                "--target",
                "mpu",
                "--package",
                "release.zip",
                "--connection-id",
                "lab-mpu",
                "--aboot-root",
                str(malicious_root),
            ]
            with (
                mock.patch.object(embedded_runtime_aboot.subprocess, "Popen") as popen,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args(arguments)
        popen.assert_not_called()

    def test_extracts_unique_mpu_release_from_combined_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            combined = workspace / "combined.zip"
            workspace.mkdir()
            release = root / "release.zip"
            with zipfile.ZipFile(release, "w") as archive:
                archive.writestr("manifest.json", "{}")
            with zipfile.ZipFile(combined, "w") as archive:
                archive.write(release, "package/mpu_build/LTE01R07A13_TRACKER_C_SDK_A.zip")

            value = stage_aboot_package(workspace, Path("combined.zip"), root / "firmware")
            selected = Path(value["package_path"])

        self.assertTrue(value["ok"])
        self.assertTrue(value["staged"])
        self.assertTrue(value["nested_extracted"])
        self.assertEqual(value["selected_member"], "package/mpu_build/LTE01R07A13_TRACKER_C_SDK_A.zip")
        self.assertEqual(selected.name, "LTE01R07A13_TRACKER_C_SDK_A.zip")
        self.assertEqual(len(value["staged_package"]["sha256"]), 64)

    def test_combined_package_rejects_symlinked_embedded_builds_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            combined = workspace / "combined.zip"
            with zipfile.ZipFile(combined, "w") as archive:
                archive.writestr("package/mpu_build/release.zip", b"not-written")
            outside = root / "outside"
            outside.mkdir()
            try:
                (workspace / "_embedded_builds").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            value = stage_aboot_package(workspace, combined, root / "firmware")

            self.assertFalse(value["ok"])
            self.assertTrue(value["blocked"])
            self.assertEqual(value["exit_code"], 5)
            self.assertEqual(value["schema_version"], "embedded-capability-result/v1")
            self.assertEqual(value["contract_version"], "1.0.0")
            self.assertEqual(value["state"], "blocked")
            self.assertIn("symlink or reparse", value["first_failure"])
            self.assertEqual(list(outside.iterdir()), [])

    def test_extracts_mpu_release_from_combined_reference_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            firmware_root = root / "firmware"
            combined = firmware_root / "combined.zip"
            workspace.mkdir()
            firmware_root.mkdir()
            release = root / "release.zip"
            with zipfile.ZipFile(release, "w") as archive:
                archive.writestr("manifest.json", "{}")
            with zipfile.ZipFile(combined, "w") as archive:
                archive.write(release, "package/mpu_build/release.zip")

            value = stage_aboot_package(workspace, combined, firmware_root)
            selected = Path(value["package_path"])

        self.assertTrue(value["ok"])
        self.assertTrue(value["nested_extracted"])
        self.assertEqual(value["source"]["path"], str(combined.resolve()))
        self.assertEqual(selected.name, "release.zip")

    def test_rejects_multiple_mpu_release_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            combined = workspace / "combined.zip"
            workspace.mkdir()
            with zipfile.ZipFile(combined, "w") as archive:
                archive.writestr("package/mpu_build/first.zip", b"first")
                archive.writestr("package/mpu_build/second.zip", b"second")

            value = stage_aboot_package(workspace, combined, root / "firmware")

        self.assertFalse(value["ok"])
        self.assertEqual(
            value["candidates"],
            ["package/mpu_build/first.zip", "package/mpu_build/second.zip"],
        )

    def test_stages_reference_package_into_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            firmware_root = root / "firmware"
            source = firmware_root / "release.zip"
            workspace.mkdir()
            firmware_root.mkdir()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("manifest.txt", "test")
            value = stage_aboot_package(workspace, source, firmware_root)
            staged = Path(value["package_path"])
        self.assertTrue(value["ok"])
        self.assertTrue(value["staged"])
        self.assertEqual(value["source"]["sha256"], value["staged_package"]["sha256"])
        self.assertIn("flash-inputs", str(staged))

    def test_reference_package_rejects_symlinked_staging_ancestor_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            firmware_root = root / "firmware"
            source = firmware_root / "release.zip"
            workspace.mkdir()
            firmware_root.mkdir()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("manifest.txt", "test")
            builds = workspace / "_embedded_builds"
            builds.mkdir()
            outside = root / "outside"
            outside.mkdir()
            try:
                (builds / "flash-inputs").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            value = stage_aboot_package(workspace, source, firmware_root)

            self.assertFalse(value["ok"])
            self.assertTrue(value["blocked"])
            self.assertEqual(value["exit_code"], 5)
            self.assertEqual(value["error"]["code"], "POLICY_BLOCKED")
            self.assertIn("symlink or reparse", value["first_failure"])
            self.assertEqual(list(outside.iterdir()), [])

    def test_reference_package_rejects_simulated_windows_junction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            firmware_root = root / "firmware"
            source = firmware_root / "release.zip"
            workspace.mkdir()
            firmware_root.mkdir()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("manifest.txt", "test")
            builds = workspace / "_embedded_builds"
            builds.mkdir()
            real_is_reparse = embedded_runtime_common.is_reparse_point

            def simulated_junction(path: Path) -> bool:
                return path == builds or real_is_reparse(path)

            with mock.patch.object(
                embedded_runtime_common,
                "is_reparse_point",
                side_effect=simulated_junction,
            ):
                value = stage_aboot_package(workspace, source, firmware_root)

            self.assertFalse(value["ok"])
            self.assertTrue(value["blocked"])
            self.assertEqual(value["schema_version"], "embedded-capability-result/v1")
            self.assertIn("symlink or reparse", value["first_failure"])
            self.assertEqual(list(builds.iterdir()), [])

    def test_reference_package_does_not_follow_precreated_temporary_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            firmware_root = root / "firmware"
            source = firmware_root / "release.zip"
            workspace.mkdir()
            firmware_root.mkdir()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("manifest.txt", "test")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            staging = workspace / "_embedded_builds" / "flash-inputs" / digest[:16]
            staging.mkdir(parents=True)
            sentinel = root / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            temporary = staging / f".release.zip.tmp-{embedded_runtime_aboot.os.getpid()}-fixed"
            try:
                temporary.symlink_to(sentinel)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            with mock.patch.object(embedded_runtime_aboot.secrets, "token_hex", return_value="fixed"):
                value = stage_aboot_package(workspace, source, firmware_root)

            self.assertFalse(value["ok"])
            self.assertTrue(value["blocked"])
            self.assertIn("symlink or reparse", value["first_failure"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_rejects_external_package_outside_firmware_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            firmware_root = root / "firmware"
            source = root / "other" / "release.zip"
            workspace.mkdir()
            firmware_root.mkdir()
            source.parent.mkdir()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("manifest.txt", "test")
            value = stage_aboot_package(workspace, source, firmware_root)
        self.assertFalse(value["ok"])
        self.assertTrue(value["blocked"])

    def test_machine_connection_binds_tool_and_firmware_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _workspace, _package, aboot_root = self.make_fixture(root)
            firmware_root = root / "approved-firmware"
            registry = self.write_registry(root, aboot_root, firmware_root=firmware_root)
            with mock.patch.object(embedded_runtime_aboot, "ABOOT_CONNECTIONS_PATH", registry):
                connection = load_aboot_connection("lab-mpu")
        self.assertEqual(connection.downloader, (aboot_root / "adownload.exe").resolve())
        self.assertEqual(connection.firmware_root, firmware_root.resolve())
        self.assertEqual(len(connection.downloader_sha256), 64)

    def test_mandatory_tool_hash_rejects_workspace_executable_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, _aboot_root = self.make_fixture(root)
            malicious_root = workspace / "tools" / "aboot"
            malicious_root.mkdir(parents=True)
            (malicious_root / "adownload.exe").write_bytes(b"malicious executable")
            registry = self.write_registry(
                root,
                malicious_root,
                digest=hashlib.sha256(b"approved executable").hexdigest(),
            )
            with (
                mock.patch.object(embedded_runtime_aboot, "ABOOT_CONNECTIONS_PATH", registry),
                mock.patch.object(embedded_runtime_aboot.subprocess, "Popen") as popen,
            ):
                value = run_aboot_flash(
                    workspace=workspace,
                    package=package,
                    connection_id="lab-mpu",
                    ports=[],
                    usb_only=True,
                    auto_enable=False,
                    speed=115200,
                    reboot=False,
                    at_fallback=False,
                    timeout=30,
                    log_dir=root / "logs",
                )
        self.assertFalse(value["ok"])
        self.assertIn("SHA-256", value["first_failure"])
        popen.assert_not_called()

    def test_symlinked_tool_is_rejected_by_machine_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_root = root / "real-aboot"
            real_root.mkdir()
            real_tool = real_root / "adownload.exe"
            real_tool.write_bytes(b"approved executable")
            linked_root = root / "linked-aboot"
            linked_root.mkdir()
            linked_tool = linked_root / "adownload.exe"
            try:
                linked_tool.symlink_to(real_tool)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            registry = self.write_registry(root, linked_root)
            with mock.patch.object(embedded_runtime_aboot, "ABOOT_CONNECTIONS_PATH", registry):
                with self.assertRaisesRegex(embedded_runtime_aboot.AbootTrustError, "symlink or reparse"):
                    load_aboot_connection("lab-mpu")

    def test_missing_machine_registry_fails_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, _aboot_root = self.make_fixture(root)
            with (
                mock.patch.object(embedded_runtime_aboot, "ABOOT_CONNECTIONS_PATH", root / "missing.json"),
                mock.patch.object(embedded_runtime_aboot.subprocess, "Popen") as popen,
            ):
                value = run_aboot_flash(
                    workspace=workspace,
                    package=package,
                    connection_id="lab-mpu",
                    ports=[],
                    usb_only=True,
                    auto_enable=False,
                    speed=115200,
                    reboot=False,
                    at_fallback=False,
                    timeout=30,
                    log_dir=root / "logs",
                )
        self.assertFalse(value["ok"])
        self.assertIn("registry", value["first_failure"])
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
