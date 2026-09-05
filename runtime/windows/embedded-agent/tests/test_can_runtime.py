from __future__ import annotations

import contextlib
import ctypes
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
BIN = RUNTIME.parent / "bin"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(BIN))

import can_middleware
import embedded_agent
import embedded_runtime_can
import zcanpro_dll


def write_driver_config(root: Path, drivers: dict) -> Path:
    path = root / "can-drivers.json"
    path.write_text(
        json.dumps({"schema_version": can_middleware.DRIVER_CONFIG_SCHEMA, "drivers": drivers}),
        encoding="utf-8",
    )
    return path


class CanMiddlewareTests(unittest.TestCase):
    def call(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(output):
            exit_code = embedded_agent.main(["--root", directory, *arguments, "--json"])
        return exit_code, json.loads(output.getvalue())

    def test_driver_list_exposes_multiple_real_adapters(self) -> None:
        exit_code, value = self.call("can", "driver-list")
        names = {item["name"] for item in value["drivers"]}
        adapters = {item["adapter"] for item in value["drivers"]}
        self.assertEqual(exit_code, 0)
        self.assertTrue({"controlcan", "zcanpro"}.issubset(names))
        self.assertTrue({"controlcan_dll", "zcanpro_dll"}.issubset(adapters))
        self.assertTrue(all("python" in item and "python_arch" in item for item in value["drivers"]))

    def test_pe_architecture_detects_x86_and_x64(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for machine, expected in ((0x014C, "x86"), (0x8664, "x64")):
                path = root / f"{expected}.dll"
                content = bytearray(256)
                content[0x3C:0x40] = (128).to_bytes(4, "little")
                content[132:134] = machine.to_bytes(2, "little")
                path.write_bytes(content)
                self.assertEqual(can_middleware.pe_architecture(path), expected)

    def test_arch_specific_packages_precede_legacy_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            architecture = can_middleware.process_architecture()
            architecture_site = root / f"site-packages-{architecture}"
            legacy_site = root / "site-packages"
            architecture_site.mkdir()
            legacy_site.mkdir()
            (architecture_site / "priority_probe.py").write_text("VALUE = 'architecture'\n", encoding="utf-8")
            (legacy_site / "priority_probe.py").write_text("raise RuntimeError('legacy selected')\n", encoding="utf-8")
            with mock.patch.object(can_middleware, "CAN_RUNTIME_ROOT", root):
                modules = can_middleware.runtime_modules(Path(sys.executable), architecture, ("priority_probe",))
        self.assertTrue(modules["priority_probe"])

    def test_can_runtime_root_cannot_be_overridden_by_task_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment["EMBEDDED_CAN_RUNTIME"] = directory
            code = f"import sys; sys.path.insert(0, {str(BIN)!r}); import can_middleware; print(can_middleware.CAN_RUNTIME_ROOT)"
            completed = subprocess.run(
                [sys.executable, "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=environment,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(Path(completed.stdout.strip()), RUNTIME.parent / "can-runtime")

    def test_runtime_modules_requires_successful_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            site = root / "site-packages-x64"
            site.mkdir()
            (site / "broken_can.py").write_text("raise AttributeError('broken dependency')\n", encoding="utf-8")
            with mock.patch.object(can_middleware, "CAN_RUNTIME_ROOT", root):
                modules = can_middleware.runtime_modules(Path(sys.executable), "x64", ("broken_can",))
        self.assertFalse(modules["broken_can"])

    def test_x86_runtime_pins_python38_typing_extensions(self) -> None:
        requirements = RUNTIME.parent / "can-runtime" / "requirements-x86.txt"
        self.assertIn("typing_extensions==4.13.2", requirements.read_text(encoding="utf-8").splitlines())

    def test_zcanpro_uses_direct_vendor_dll_adapter(self) -> None:
        spec = can_middleware.DRIVERS["zcanpro"]

        self.assertEqual(spec.adapter, "zcanpro_dll")
        self.assertEqual(spec.required_modules, ("can",))
        self.assertTrue(spec.requires_dll)

    def test_zcanpro_direct_adapter_opens_starts_transmits_and_closes(self) -> None:
        events: list[tuple] = []

        class FakeFunction:
            def __init__(self, callback):
                self.callback = callback
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.callback(*args)

        def transmit(_handle, pointer, count):
            value = ctypes.cast(pointer, ctypes.POINTER(zcanpro_dll.ZCanTransmitData)).contents
            events.append(("transmit", value.frame.can_id, bytes(value.frame.data[: value.frame.can_dlc]), count))
            return 1

        fake_dll = types.SimpleNamespace(
            ZCAN_OpenDevice=FakeFunction(lambda device_type, index, reserved: events.append(("open", device_type, index, reserved)) or 0x100),
            ZCAN_CloseDevice=FakeFunction(lambda handle: events.append(("close", handle)) or 1),
            ZCAN_InitCAN=FakeFunction(lambda handle, channel, config: events.append(("init", handle, channel)) or 0x200),
            ZCAN_StartCAN=FakeFunction(lambda handle: events.append(("start", handle)) or 1),
            ZCAN_ResetCAN=FakeFunction(lambda handle: events.append(("reset", handle)) or 1),
            ZCAN_Transmit=FakeFunction(transmit),
            ZCAN_Receive=FakeFunction(lambda *_args: 0),
        )
        with mock.patch.object(zcanpro_dll, "load_library", return_value=(fake_dll, [])):
            device = zcanpro_dll.ZCanProDevice("zlgcan.dll", "ZCAN_USBCAN2", 0, 0)
            device.open(500000)
            device.send(0x705, b"\x10\x01")
            device.close()

        self.assertIn(("open", 4, 0, 0), events)
        self.assertIn(("init", 0x100, 0), events)
        self.assertIn(("start", 0x200), events)
        self.assertIn(("transmit", 0x705, b"\x10\x01", 1), events)
        self.assertIn(("reset", 0x200), events)
        self.assertIn(("close", 0x100), events)

    def test_controlcan_open_bus_uses_vendor_dll_adapter(self) -> None:
        events: list[tuple] = []

        class FakeBusABC:
            def __init__(self, channel: int, **_kwargs) -> None:
                self.channel = channel

            def shutdown(self) -> None:
                events.append(("base-shutdown",))

        class FakeMessage:
            def __init__(self, arbitration_id: int, data: bytes, is_extended_id: bool = False, **_kwargs) -> None:
                self.arbitration_id = arbitration_id
                self.data = data
                self.is_extended_id = is_extended_id

        class FakeControlCan:
            def __init__(self, dll_path: str, dev_type: int, dev_index: int, can_index: int) -> None:
                events.append(("init", dll_path, dev_type, dev_index, can_index))

            def open(self, bitrate: int) -> None:
                events.append(("open", bitrate))

            def send(self, can_id: int, data: bytes, extended: bool = False) -> None:
                events.append(("send", can_id, data, extended))

            def recv_many(self, timeout_ms: int) -> list:
                events.append(("recv", timeout_ms))
                return []

            def close(self) -> None:
                events.append(("close",))

        def reject_canalystii(**_kwargs):
            raise AssertionError("python-can canalystii backend must not be used for ControlCAN.dll")

        fake_can = types.SimpleNamespace(BusABC=FakeBusABC, Message=FakeMessage, Bus=reject_canalystii)
        fake_controlcan = types.SimpleNamespace(ControlCan=FakeControlCan, parse_dev_type=lambda value: int(value, 0))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dll = root / "ControlCAN.dll"
            dll.write_bytes(b"not-a-real-pe")
            config = write_driver_config(root, {"controlcan": {"dll": str(dll)}})
            with (
                mock.patch.dict(sys.modules, {"can": fake_can, "pc_uds_ecu_sim": fake_controlcan}),
                mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config),
                mock.patch.object(can_middleware, "pe_architecture", return_value="unknown"),
            ):
                _, bus = can_middleware.open_bus("controlcan", channel=0, bitrate=500000, device_index=0)
                bus.send(FakeMessage(0x705, b"\x02\x10\x01"))
                bus.shutdown()

        self.assertIn(("open", 500000), events)
        self.assertIn(("send", 0x705, b"\x02\x10\x01", False), events)
        self.assertIn(("close",), events)

    def test_device_probe_reports_only_opened_selectors(self) -> None:
        backend = {
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "results": [
                        {"type": 3, "index": 0, "open": 0},
                        {"type": 20, "index": 1, "open": 1},
                    ]
                }
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dll = root / "ControlCAN.dll"
            dll.write_bytes(b"trusted-driver")
            config = write_driver_config(root, {"controlcan": {"dll": str(dll)}})
            with (
                mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config),
                mock.patch.object(embedded_runtime_can, "_run_tool", return_value=backend),
            ):
                exit_code, value = self.call("can", "device-probe", "--driver", "controlcan")
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["matches"], [{"device_model": 20, "device_index": 1}])

    def test_probe_json_parser_ignores_vendor_warning_after_json(self) -> None:
        value = embedded_runtime_can._parse_backend_json('{"ok":true,"results":[]}\n[WRN] vendor log failed\n')

        self.assertTrue(value["ok"])

    def test_can_failure_summary_prefers_timeout_over_request_echo(self) -> None:
        summary = embedded_runtime_can._failure_text("", "> 10 01\n  TIMEOUT\n")

        self.assertEqual(summary, "TIMEOUT")

    def test_zcanpro_device_probe_rejects_network_style_false_positive(self) -> None:
        backend = {
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "results": [
                        {"type": 17, "index": 0, "open": 1, "device_info": 1, "physical": False},
                        {"type": 4, "index": 0, "open": 1, "device_info": 1, "physical": True},
                    ]
                }
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dll = root / "zlgcan.dll"
            dll.write_bytes(b"trusted-driver")
            config = write_driver_config(root, {"zcanpro": {"dll": str(dll)}})
            with (
                mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config),
                mock.patch.object(embedded_runtime_can, "_run_tool", return_value=backend),
            ):
                exit_code, value = self.call("can", "device-probe", "--driver", "zcanpro")
        self.assertEqual(exit_code, 0)
        self.assertEqual(value["matches"], [{"device_model": 4, "device_index": 0}])

    def test_zcanpro_device_probe_closes_handle_when_device_info_fails(self) -> None:
        spec = importlib.util.spec_from_file_location("probe_zcanpro_close_test", BIN / "probe-zcanpro.py")
        assert spec and spec.loader
        probe_zcanpro = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe_zcanpro)
        events: list[str] = []

        def fail_device_info(*_args):
            events.append("device-info")
            raise OSError("device info failed")

        fake_dll = types.SimpleNamespace(
            ZCAN_OpenDevice=lambda *_args: events.append("open") or 0x100,
            ZCAN_GetDeviceInf=fail_device_info,
            ZCAN_CloseDevice=lambda *_args: events.append("close") or 1,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dll = root / "zlgcan.dll"
            dll.write_bytes(b"trusted-driver")
            config = write_driver_config(root, {"zcanpro": {"dll": str(dll)}})
            with (
                mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config),
                mock.patch.object(probe_zcanpro, "load_library", return_value=(fake_dll, [])),
                mock.patch.object(probe_zcanpro, "bind_library"),
                mock.patch.object(probe_zcanpro, "pe_machine", return_value="unknown"),
            ):
                results = probe_zcanpro.probe(dll, [4], [0])

        self.assertEqual(events, ["open", "device-info", "close"])
        self.assertEqual(results[0]["close"], 1)
        self.assertIn("device info failed", results[0]["error"])

    def test_workspace_dll_is_rejected_before_subprocess_or_ctypes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            trusted = root / "vendor" / "zlgcan.dll"
            trusted.parent.mkdir()
            trusted.write_bytes(b"trusted-driver")
            malicious = root / "workspace" / "zlgcan.dll"
            malicious.parent.mkdir()
            malicious.write_bytes(b"malicious-driver")
            config = write_driver_config(root, {"zcanpro": {"dll": str(trusted)}})
            with (
                mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config),
                mock.patch.object(embedded_runtime_can, "_run_tool") as run_tool,
                mock.patch.object(ctypes, "CDLL", side_effect=AssertionError("ctypes must not run")),
            ):
                exit_code, value = self.call("can", "device-probe", "--driver", "zcanpro", "--dll", str(malicious))

        self.assertEqual(exit_code, 2)
        self.assertFalse(value["ok"])
        self.assertIn("not allowed", value["first_failure"])
        run_tool.assert_not_called()

    def test_driver_hash_mismatch_makes_capability_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dll = root / "ControlCAN.dll"
            dll.write_bytes(b"actual")
            config = write_driver_config(root, {"controlcan": {"dll": str(dll), "sha256": hashlib.sha256(b"expected").hexdigest()}})
            with mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config):
                inventory = can_middleware.driver_inventory("controlcan")[0]
        self.assertFalse(inventory["ready"])
        self.assertIn("sha256", "; ".join(inventory["blockers"]))

    def test_symlinked_driver_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            real_dll = root / "vendor" / "ControlCAN.dll"
            real_dll.parent.mkdir()
            real_dll.write_bytes(b"trusted-driver")
            link = root / "ControlCAN.dll"
            try:
                link.symlink_to(real_dll)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            config = write_driver_config(root, {"controlcan": {"dll": str(link)}})
            with mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config):
                inventory = can_middleware.driver_inventory("controlcan")[0]
        self.assertFalse(inventory["ready"])
        self.assertIn("symlink or reparse", "; ".join(inventory["blockers"]))

    def test_zcanpro_loader_rejects_unconfigured_path_before_ctypes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            trusted = root / "vendor" / "zlgcan.dll"
            trusted.parent.mkdir()
            trusted.write_bytes(b"trusted-driver")
            malicious = root / "workspace" / "zlgcan.dll"
            malicious.parent.mkdir()
            malicious.write_bytes(b"malicious-driver")
            config = write_driver_config(root, {"zcanpro": {"dll": str(trusted)}})
            with (
                mock.patch.object(can_middleware, "DRIVER_CONFIG_PATH", config),
                mock.patch.object(zcanpro_dll.ctypes, "CDLL") as loader,
            ):
                with self.assertRaisesRegex(can_middleware.DriverTrustError, "not allowed"):
                    zcanpro_dll.load_library(str(malicious))
        loader.assert_not_called()

    def test_self_test_does_not_require_can_driver(self) -> None:
        exit_code, value = self.call("can", "self-test")
        self.assertEqual(exit_code, 0)
        self.assertTrue(value["ok"])
        self.assertIn("self-test ok", value["backend"]["stdout"])

    def test_send_gate_closes_before_driver_access(self) -> None:
        exit_code, value = self.call("can", "send", "--driver", "controlcan", "--frame", "0x123#01")
        self.assertEqual(exit_code, 2)
        self.assertTrue(value["requires_human_confirm"])

    def test_monitor_must_be_bounded(self) -> None:
        exit_code, value = self.call("can", "monitor", "--driver", "controlcan")
        self.assertEqual(exit_code, 2)
        self.assertIn("bounded", value["first_failure"])

    def test_uds_ecu_must_be_bounded_before_gate(self) -> None:
        exit_code, value = self.call("can", "uds-ecu", "--driver", "controlcan")
        self.assertEqual(exit_code, 2)
        self.assertIn("bounded", value["first_failure"])


if __name__ == "__main__":
    unittest.main()
