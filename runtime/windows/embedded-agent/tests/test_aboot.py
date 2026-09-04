from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_aboot import normalize_ports, normalize_windows_exit_code, prepare_aboot_flash, stage_aboot_package  # noqa: E402
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

    def test_builds_bounded_usb_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, package, aboot_root = self.make_fixture(Path(directory))
            value = prepare_aboot_flash(
                workspace=workspace,
                package=package,
                aboot_root=aboot_root,
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
                aboot_root=aboot_root,
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
            workspace, package, aboot_root = self.make_fixture(Path(directory))
            value = prepare_aboot_flash(
                workspace=workspace,
                package=package,
                aboot_root=aboot_root,
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
                "--port",
                "COM3",
                "--require-confirm",
                "--confirm",
            ]
        )
        self.assertEqual(args.target, "mpu")
        self.assertEqual(args.port, ["COM3"])
        self.assertEqual(args.package, Path("release.zip"))

    def test_resolves_relative_package_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, _ = self.make_fixture(root)
            value = stage_aboot_package(workspace, package.relative_to(workspace), root / "firmware")
        self.assertTrue(value["ok"])
        self.assertEqual(Path(value["package_path"]), package.resolve())

    def test_resolves_relative_aboot_root_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, package, _ = self.make_fixture(root)
            aboot_root = workspace / "tools" / "aboot"
            aboot_root.mkdir(parents=True)
            (aboot_root / "adownload.exe").write_bytes(b"test executable")

            value = prepare_aboot_flash(
                workspace=workspace,
                package=package,
                aboot_root=Path("tools/aboot"),
                ports=[],
                usb_only=True,
                auto_enable=False,
                speed=115200,
                reboot=False,
                at_fallback=False,
            )

        self.assertTrue(value["ok"])
        self.assertEqual(Path(value["tool"]["path"]), (aboot_root / "adownload.exe").resolve())

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


if __name__ == "__main__":
    unittest.main()
