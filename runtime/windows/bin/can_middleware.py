"""CAN Runtime Module with pluggable Windows Driver Adapters.

The public Interface is intentionally small: inventory drivers and open a
python-can compatible bus.  DLL discovery, process architecture and vendor
configuration stay behind this seam.
"""

from __future__ import annotations

import json
import os
import subprocess
import struct
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CAN_RUNTIME_ROOT = Path(os.environ.get("EMBEDDED_CAN_RUNTIME", str(Path(__file__).resolve().parent.parent / "can-runtime")))
CAN_SITE_PACKAGES = CAN_RUNTIME_ROOT / f"site-packages-{('x86' if struct.calcsize('P') == 4 else 'x64')}"
CAN_LEGACY_SITE_PACKAGES = CAN_RUNTIME_ROOT / "site-packages"
# Insert in reverse because each path is prepended. The architecture-specific
# environment must win over the legacy compatibility directory.
for site_packages in (CAN_LEGACY_SITE_PACKAGES, CAN_SITE_PACKAGES):
    if site_packages.is_dir() and str(site_packages) not in sys.path:
        sys.path.insert(0, str(site_packages))


@dataclass(frozen=True)
class DriverSpec:
    name: str
    adapter: str
    description: str
    dll_candidates: tuple[str, ...]
    required_modules: tuple[str, ...]
    default_device_model: str
    runtime_candidates: tuple[str, ...]


DRIVERS = {
    "controlcan": DriverSpec(
        name="controlcan",
        adapter="controlcan_dll",
        description="ZLG classic ControlCAN.dll Driver Adapter",
        dll_candidates=(
            os.environ.get("EMBEDDED_CONTROLCAN_DLL", ""),
            str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ZLG" / "ControlCAN.dll"),
        ),
        required_modules=("can",),
        default_device_model="4",
        runtime_candidates=(os.environ.get("EMBEDDED_CAN_PYTHON", ""), sys.executable),
    ),
    "zcanpro": DriverSpec(
        name="zcanpro",
        adapter="zcanpro_dll",
        description="ZCANPro direct zlgcan.dll Driver Adapter",
        dll_candidates=(
            os.environ.get("EMBEDDED_ZCANPRO_DLL", ""),
            str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ZCANPRO" / "zlgcan.dll"),
        ),
        required_modules=("can",),
        default_device_model="ZCAN_USBCAN2",
        runtime_candidates=(os.environ.get("EMBEDDED_CAN_PYTHON", ""), sys.executable),
    ),
    "virtual": DriverSpec(
        name="virtual",
        adapter="virtual",
        description="python-can in-memory Adapter for tests",
        dll_candidates=(),
        required_modules=("can",),
        default_device_model="virtual",
        runtime_candidates=(sys.executable,),
    ),
}


def process_architecture() -> str:
    return "x86" if struct.calcsize("P") == 4 else "x64"


def pe_architecture(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0x3C)
            pe_offset = int.from_bytes(handle.read(4), "little")
            handle.seek(pe_offset + 4)
            machine = int.from_bytes(handle.read(2), "little")
    except OSError:
        return "unknown"
    return {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}.get(machine, f"0x{machine:04X}")


def first_file(values: Iterable[str]) -> Path | None:
    return next((Path(value) for value in values if Path(value).is_file()), None)


def runtime_architecture(path: Path) -> str:
    if path.resolve() == Path(sys.executable).resolve():
        return process_architecture()
    return pe_architecture(path)


def select_runtime(spec: DriverSpec, dll_arch: str | None) -> tuple[Path | None, str | None]:
    candidates = [Path(value) for value in spec.runtime_candidates if Path(value).is_file()]
    if not candidates:
        return None, None
    if dll_arch in {"x86", "x64"}:
        matched = next((path for path in candidates if runtime_architecture(path) == dll_arch), None)
        if matched:
            return matched, dll_arch
    selected = candidates[0]
    return selected, runtime_architecture(selected)


def runtime_modules(runtime: Path | None, runtime_arch: str | None, modules: tuple[str, ...]) -> dict[str, bool]:
    if runtime is None:
        return {module: False for module in modules}
    site = CAN_RUNTIME_ROOT / f"site-packages-{runtime_arch}"
    legacy = CAN_RUNTIME_ROOT / "site-packages"
    code = """
import importlib
import json
import sys

result = {}
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except Exception:
        result[name] = False
    else:
        result[name] = True
print(json.dumps(result))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in (site, legacy) if path.is_dir())
    try:
        completed = subprocess.run(
            [str(runtime), "-c", code, *modules],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
            env=environment,
        )
        value = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        value = {}
    return {module: bool(value.get(module)) for module in modules}


def driver_inventory(name: str | None = None) -> list[dict[str, Any]]:
    selected = [DRIVERS[name]] if name else list(DRIVERS.values())
    values: list[dict[str, Any]] = []
    for spec in selected:
        dll = first_file(spec.dll_candidates)
        dll_arch = pe_architecture(dll) if dll else None
        runtime, runtime_arch = select_runtime(spec, dll_arch)
        modules = runtime_modules(runtime, runtime_arch, spec.required_modules)
        architecture_ok = dll_arch in {None, "unknown", runtime_arch}
        ready = (dll is not None or not spec.dll_candidates) and all(modules.values()) and architecture_ok
        blockers: list[str] = []
        if spec.dll_candidates and dll is None:
            blockers.append("driver DLL not found")
        for module, available in modules.items():
            if not available:
                blockers.append(f"Python module missing or failed to import: {module}")
        if not architecture_ok:
            blockers.append(f"DLL is {dll_arch}, selected Python is {runtime_arch}")
        if runtime is None:
            blockers.append("matching Python runtime not found")
        values.append(
            {
                "name": spec.name,
                "adapter": spec.adapter,
                "description": spec.description,
                "ready": ready,
                "process_arch": process_architecture(),
                "python": str(runtime) if runtime else None,
                "python_arch": runtime_arch,
                "dll": str(dll) if dll else None,
                "dll_arch": dll_arch,
                "dll_candidates": list(spec.dll_candidates),
                "required_modules": modules,
                "default_device_model": spec.default_device_model,
                "runtime_root": str(CAN_RUNTIME_ROOT),
                "blockers": blockers,
            }
        )
    return values


def driver_runtime(name: str) -> str:
    inventory = driver_inventory(name)[0]
    if not inventory["python"]:
        raise RuntimeError(f"No Python runtime found for CAN driver: {name}")
    return str(inventory["python"])


def _add_dll_directory(path: Path) -> Any | None:
    directory = path.parent
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        return os.add_dll_directory(str(directory))
    return None


def _open_controlcan_bus(
    can: Any,
    dll_path: Path,
    *,
    channel: int,
    bitrate: int,
    device_model: str,
    device_index: int,
) -> Any:
    from pc_uds_ecu_sim import ControlCan, parse_dev_type

    class ControlCanDllBus(can.BusABC):
        def __init__(self) -> None:
            device = ControlCan(str(dll_path), parse_dev_type(device_model), device_index, channel)
            device.open(bitrate)
            super().__init__(channel=channel)
            self.channel_info = (
                f"ControlCAN.dll type={device_model} device={device_index} "
                f"channel={channel} bitrate={bitrate}"
            )
            self._frames: deque[Any] = deque()
            self._closed = False
            self._device = device

        def fileno(self) -> int:
            raise NotImplementedError("ControlCAN.dll does not expose a selectable file descriptor")

        def send(self, msg: Any, timeout: float | None = None) -> None:
            del timeout
            if getattr(msg, "is_fd", False):
                raise ValueError("ControlCAN.dll Adapter supports classic CAN only")
            self._device.send(msg.arbitration_id, bytes(msg.data), bool(msg.is_extended_id))

        def _recv_internal(self, timeout: float | None) -> tuple[Any | None, bool]:
            if not self._frames:
                wait_seconds = 1.0 if timeout is None else max(0.0, timeout)
                self._frames.extend(self._device.recv_many(int(wait_seconds * 1000)))
            if not self._frames:
                return None, False
            frame = self._frames.popleft()
            message = can.Message(
                arbitration_id=int(frame.ID),
                data=bytes(frame.Data[: int(frame.DataLen)]),
                is_extended_id=bool(frame.ExternFlag),
                is_remote_frame=bool(frame.RemoteFlag),
                channel=channel,
                is_rx=True,
            )
            return message, False

        def shutdown(self) -> None:
            if not self._closed:
                self._closed = True
                self._device.close()
            super().shutdown()

    return ControlCanDllBus()


def _open_zcanpro_bus(
    can: Any,
    dll_path: Path,
    *,
    channel: int,
    bitrate: int,
    device_model: str,
    device_index: int,
) -> Any:
    from zcanpro_dll import CAN_EFF_FLAG, CAN_RTR_FLAG, ZCanProDevice

    class ZCanProDllBus(can.BusABC):
        def __init__(self) -> None:
            device = ZCanProDevice(str(dll_path), device_model, device_index, channel)
            device.open(bitrate)
            super().__init__(channel=channel)
            self.channel_info = (
                f"ZCANPro zlgcan.dll type={device_model} device={device_index} "
                f"channel={channel} bitrate={bitrate}"
            )
            self._frames: deque[Any] = deque()
            self._closed = False
            self._device = device

        def fileno(self) -> int:
            raise NotImplementedError("zlgcan.dll does not expose a selectable file descriptor")

        def send(self, msg: Any, timeout: float | None = None) -> None:
            del timeout
            if getattr(msg, "is_fd", False):
                raise ValueError("ZCANPro direct Adapter supports classic CAN only")
            self._device.send(msg.arbitration_id, bytes(msg.data), bool(msg.is_extended_id))

        def _recv_internal(self, timeout: float | None) -> tuple[Any | None, bool]:
            if not self._frames:
                wait_seconds = 1.0 if timeout is None else max(0.0, timeout)
                self._frames.extend(self._device.recv_many(int(wait_seconds * 1000)))
            if not self._frames:
                return None, False
            value = self._frames.popleft()
            raw_id = int(value.frame.can_id)
            message = can.Message(
                arbitration_id=raw_id & (0x1FFFFFFF if raw_id & CAN_EFF_FLAG else 0x7FF),
                data=bytes(value.frame.data[: int(value.frame.can_dlc)]),
                is_extended_id=bool(raw_id & CAN_EFF_FLAG),
                is_remote_frame=bool(raw_id & CAN_RTR_FLAG),
                timestamp=float(value.timestamp) / 1_000_000.0,
                channel=channel,
                is_rx=True,
            )
            return message, False

        def shutdown(self) -> None:
            if not self._closed:
                self._closed = True
                self._device.close()
            super().shutdown()

    return ZCanProDllBus()


def open_bus(
    driver: str,
    *,
    channel: int,
    bitrate: int,
    dll_path: str | None = None,
    device_model: str | None = None,
    device_index: int = 0,
) -> tuple[Any, Any]:
    if driver not in DRIVERS:
        raise ValueError(f"Unknown CAN driver: {driver}")
    spec = DRIVERS[driver]
    inventory = driver_inventory(driver)[0]
    selected_dll = Path(dll_path) if dll_path else (Path(inventory["dll"]) if inventory["dll"] else None)
    if selected_dll and not selected_dll.is_file():
        raise RuntimeError(f"CAN driver DLL not found: {selected_dll}")
    if selected_dll:
        dll_arch = pe_architecture(selected_dll)
        if dll_arch not in {"unknown", process_architecture()}:
            raise RuntimeError(f"CAN driver DLL is {dll_arch}, current Python is {process_architecture()}")
        _add_dll_directory(selected_dll)

    try:
        import can  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-can is not installed in the CAN Runtime") from exc

    if driver == "virtual":
        return can, can.Bus(interface="virtual", channel=channel, receive_own_messages=True)
    if driver == "controlcan":
        if selected_dll is None:
            raise RuntimeError("ControlCAN.dll not found")
        return can, _open_controlcan_bus(
            can,
            selected_dll,
            channel=channel,
            bitrate=bitrate,
            device_model=device_model or spec.default_device_model,
            device_index=device_index,
        )

    if selected_dll is None:
        raise RuntimeError("ZCANPro zlgcan.dll not found")
    return can, _open_zcanpro_bus(
        can,
        selected_dll,
        channel=channel,
        bitrate=bitrate,
        device_model=device_model or spec.default_device_model,
        device_index=device_index,
    )
