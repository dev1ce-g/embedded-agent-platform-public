from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import embedded_agent
import embedded_runtime_device


class DeviceProxyTests(unittest.TestCase):
    project = "test-project"
    serial = "9CE7B521"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / "agent"
        self.workspace = self.root.parent / "workspace"
        self.workspace.mkdir()
        project_dir = self.root / "projects" / self.project
        project_dir.mkdir(parents=True)
        background = {
            "project_id": self.project,
            "background_id": "bg-1",
            "workspace": str(self.workspace),
        }
        (project_dir / "background.json").write_text(json.dumps(background), encoding="utf-8")

    def call(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(["--root", str(self.root), *arguments, "--json"])
        return exit_code, json.loads(output.getvalue())

    @staticmethod
    def completed(command: list[str], stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    def test_device_list_reports_online_device(self) -> None:
        output = (
            b"List of devices attached\r\n"
            b"9CE7B521 device product:n725a model:N725A transport_id:52\r\n"
        )
        with mock.patch.object(embedded_runtime_device, "adb_executable", return_value="adb.exe"), mock.patch.object(
            embedded_agent.subprocess,
            "run",
            return_value=self.completed(["adb.exe", "devices", "-l"], stdout=output),
        ):
            exit_code, value = self.call("device", "list", "--project", self.project)

        self.assertEqual(exit_code, 0)
        self.assertTrue(value["read_only"])
        self.assertEqual(value["devices"][0]["serial"], self.serial)
        self.assertEqual(value["devices"][0]["properties"]["transport_id"], "52")

    def test_serial_inspect_reports_driver_and_holder(self) -> None:
        responses = {
            ("devices", "-l"): b"List of devices attached\n9CE7B521 device transport_id:52\n",
            ("-s", self.serial, "shell", "ls", "-l", "/dev/ttyS2"): b"crw-rw---- 1 root dialout 4, 66 /dev/ttyS2\n",
            ("-s", self.serial, "shell", "readlink", "-f", "/sys/class/tty/ttyS2/device"): b"/sys/devices/platform/soc/d4000000.apb/pxa2xx-uart.3\n",
            ("-s", self.serial, "shell", "readlink", "-f", "/sys/class/tty/ttyS2/device/driver"): b"/sys/bus/platform/drivers/pxa2xx-uart\n",
            ("-s", self.serial, "shell", "cat", "/sys/class/tty/ttyS2/device/uevent"): b"DRIVER=pxa2xx-uart\nOF_FULLNAME=/soc/apb@d4000000/uart@d401f000\nOF_ALIAS_0=serial2\n",
            ("-s", self.serial, "shell", "ls", "-l", "/proc/[0-9]*/fd/*"): b"lrwx------ 1 root root 64 /proc/2542/fd/6 -> /dev/ttyS2\n",
            ("-s", self.serial, "shell", "cat", "/proc/2542/cmdline"): b"/vendor/app/hq/bin/hubs_app\x00",
        }

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess:
            arguments = tuple(command[1:])
            return self.completed(command, stdout=responses[arguments])

        with mock.patch.object(embedded_runtime_device, "adb_executable", return_value="adb.exe"), mock.patch.object(
            embedded_agent.subprocess,
            "run",
            side_effect=fake_run,
        ):
            exit_code, value = self.call("device", "serial-inspect", "--project", self.project, "--tty", "ttyS2")

        self.assertEqual(exit_code, 0)
        self.assertTrue(value["read_only"])
        self.assertEqual(value["tty"], "ttyS2")
        self.assertEqual(value["driver"], "/sys/bus/platform/drivers/pxa2xx-uart")
        self.assertEqual(value["uevent"]["OF_ALIAS_0"], "serial2")
        self.assertEqual(value["holders"], [{"pid": 2542, "fd": 6, "command": "/vendor/app/hq/bin/hubs_app"}])

    def test_serial_inspect_rejects_invalid_tty_before_adb(self) -> None:
        with mock.patch.object(embedded_runtime_device, "run_adb") as run_adb:
            exit_code, value = self.call("device", "serial-inspect", "--project", self.project, "--tty", "../../data")

        self.assertEqual(exit_code, 2)
        self.assertIn("--tty must be", value["first_failure"])
        run_adb.assert_not_called()

    def test_serial_inspect_requires_serial_when_multiple_devices_are_online(self) -> None:
        output = b"List of devices attached\nfirst device\nsecond device\n"
        with mock.patch.object(embedded_runtime_device, "adb_executable", return_value="adb.exe"), mock.patch.object(
            embedded_agent.subprocess,
            "run",
            return_value=self.completed(["adb.exe", "devices", "-l"], stdout=output),
        ):
            exit_code, value = self.call("device", "serial-inspect", "--project", self.project, "--tty", "ttyS2")

        self.assertEqual(exit_code, 4)
        self.assertIn("Multiple online ADB devices", value["first_failure"])


if __name__ == "__main__":
    unittest.main()
