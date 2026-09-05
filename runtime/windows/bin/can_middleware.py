"""CAN Runtime Module with pluggable Windows Driver Adapters.

The public Interface is intentionally small: inventory drivers and open a
python-can compatible bus.  DLL discovery, process architecture and vendor
configuration stay behind this seam.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import struct
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WINDOWS_RUNTIME_ROOT = Path(__file__).resolve().parent.parent
CAN_RUNTIME_ROOT = WINDOWS_RUNTIME_ROOT / "can-runtime"
DRIVER_CONFIG_PATH = WINDOWS_RUNTIME_ROOT / "can-drivers.json"
DRIVER_CONFIG_SCHEMA = "embedded-can-driver-config/v1"
MAX_DRIVER_CONFIG_BYTES = 64 * 1024
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
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
    requires_dll: bool
    required_modules: tuple[str, ...]
    default_device_model: str


DRIVERS = {
    "controlcan": DriverSpec(
        name="controlcan",
        adapter="controlcan_dll",
        description="ZLG classic ControlCAN.dll Driver Adapter",
        requires_dll=True,
        required_modules=("can",),
        default_device_model="4",
    ),
    "zcanpro": DriverSpec(
        name="zcanpro",
        adapter="zcanpro_dll",
        description="ZCANPro direct zlgcan.dll Driver Adapter",
        requires_dll=True,
        required_modules=("can",),
        default_device_model="ZCAN_USBCAN2",
    ),
    "virtual": DriverSpec(
        name="virtual",
        adapter="virtual",
        description="python-can in-memory Adapter for tests",
        requires_dll=False,
        required_modules=("can",),
        default_device_model="virtual",
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


class DriverTrustError(RuntimeError):
    """Raised before native code is loaded when machine trust is incomplete."""


def _is_symlink_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _canonical_regular_file(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise DriverTrustError(f"{label} must be an absolute path")
    lexical = Path(os.path.abspath(str(expanded)))
    for component in (lexical, *lexical.parents):
        if _is_symlink_or_reparse(component):
            raise DriverTrustError(f"{label} must not use a symlink or reparse point: {component}")
    try:
        canonical = lexical.resolve(strict=True)
        info = canonical.stat()
    except OSError as exc:
        raise DriverTrustError(f"{label} is unavailable: {lexical}: {exc}") from exc
    if not _same_path(lexical, canonical):
        raise DriverTrustError(f"{label} must already be canonical: {lexical}")
    if not stat.S_ISREG(info.st_mode):
        raise DriverTrustError(f"{label} must be a regular file: {canonical}")
    return canonical


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_hash(path: Path, expected: Any, label: str) -> tuple[str, bool]:
    if expected is not None and (not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected)):
        raise DriverTrustError(f"{label} sha256 must be a full 64-character hexadecimal digest")
    try:
        actual = _sha256_file(path)
    except OSError as exc:
        raise DriverTrustError(f"{label} could not be hashed: {exc}") from exc
    if expected is not None and actual.lower() != expected.lower():
        raise DriverTrustError(f"{label} sha256 does not match the machine configuration")
    return actual, expected is not None


def load_driver_config() -> tuple[dict[str, Any], Path]:
    """Load the fixed, Runtime-adjacent machine configuration.

    No CLI or environment option can choose this file. That property is the
    trust boundary between a task caller and the machine operator.
    """

    path = _canonical_regular_file(DRIVER_CONFIG_PATH, "CAN driver configuration")
    if path.stat().st_size > MAX_DRIVER_CONFIG_BYTES:
        raise DriverTrustError(f"CAN driver configuration exceeds {MAX_DRIVER_CONFIG_BYTES} bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DriverTrustError(f"CAN driver configuration is invalid: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != DRIVER_CONFIG_SCHEMA:
        raise DriverTrustError(f"CAN driver configuration schema must be {DRIVER_CONFIG_SCHEMA}")
    if not isinstance(value.get("drivers"), dict):
        raise DriverTrustError("CAN driver configuration must contain a drivers object")
    return value, path


def configured_driver(name: str) -> tuple[dict[str, Any], Path]:
    if name not in DRIVERS:
        raise DriverTrustError(f"Unknown CAN driver: {name}")
    value, config_path = load_driver_config()
    entry = value["drivers"].get(name)
    if not isinstance(entry, dict):
        raise DriverTrustError(f"CAN driver is not present in machine configuration: {name}")
    return entry, config_path


def require_trusted_driver_path(name: str, requested_path: str | Path | None = None) -> Path | None:
    """Resolve a native DLL solely from the fixed machine configuration."""

    if name not in DRIVERS:
        raise DriverTrustError(f"Unknown CAN driver: {name}")
    spec = DRIVERS[name]
    if not spec.requires_dll:
        if requested_path:
            raise DriverTrustError(f"CAN driver {name} does not accept a DLL path")
        return None
    entry, _config_path = configured_driver(name)
    configured = entry.get("dll")
    if not isinstance(configured, str) or not configured.strip():
        raise DriverTrustError(f"CAN driver machine configuration has no DLL path: {name}")
    trusted = _canonical_regular_file(Path(configured), f"{name} driver DLL")
    _verify_hash(trusted, entry.get("sha256"), f"{name} driver DLL")
    if requested_path is not None:
        requested = Path(requested_path).expanduser()
        if not requested.is_absolute() or not _same_path(requested, trusted):
            raise DriverTrustError(
                f"Caller-provided DLL path is not allowed for {name}; use the machine-configured driver"
            )
    return trusted


def require_trusted_runtime_path(name: str) -> Path:
    if name == "virtual":
        return Path(sys.executable).resolve()
    entry, _config_path = configured_driver(name)
    configured = entry.get("python")
    if configured is None:
        return Path(sys.executable).resolve()
    if not isinstance(configured, str) or not configured.strip():
        raise DriverTrustError(f"Configured Python path is invalid for CAN driver: {name}")
    runtime = _canonical_regular_file(Path(configured), f"{name} Python runtime")
    _verify_hash(runtime, entry.get("python_sha256"), f"{name} Python runtime")
    return runtime


def runtime_architecture(path: Path) -> str:
    if path.resolve() == Path(sys.executable).resolve():
        return process_architecture()
    return pe_architecture(path)


def select_runtime(name: str) -> tuple[Path | None, str | None, str | None]:
    try:
        selected = require_trusted_runtime_path(name)
    except DriverTrustError as exc:
        return None, None, str(exc)
    return selected, runtime_architecture(selected), None


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
        trust_error: str | None = None
        config_path: str | None = None
        dll: Path | None = None
        dll_sha256: str | None = None
        hash_required = False
        if spec.requires_dll:
            try:
                entry, trusted_config = configured_driver(spec.name)
                config_path = str(trusted_config)
                dll = require_trusted_driver_path(spec.name)
                assert dll is not None
                try:
                    dll_sha256 = _sha256_file(dll)
                except OSError as exc:
                    raise DriverTrustError(f"{spec.name} driver DLL could not be hashed: {exc}") from exc
                hash_required = entry.get("sha256") is not None
            except DriverTrustError as exc:
                trust_error = str(exc)
        dll_arch = pe_architecture(dll) if dll else None
        runtime, runtime_arch, runtime_error = select_runtime(spec.name)
        modules = runtime_modules(runtime, runtime_arch, spec.required_modules)
        architecture_ok = dll_arch in {None, "unknown", runtime_arch}
        ready = (dll is not None or not spec.requires_dll) and all(modules.values()) and architecture_ok and runtime_error is None
        blockers: list[str] = []
        if trust_error:
            blockers.append(trust_error)
        if runtime_error and runtime_error != trust_error:
            blockers.append(runtime_error)
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
                "dll_sha256": dll_sha256,
                "dll_hash_required": hash_required,
                "driver_config": config_path or str(DRIVER_CONFIG_PATH),
                "machine_configured": not spec.requires_dll or trust_error is None,
                "required_modules": modules,
                "default_device_model": spec.default_device_model,
                "runtime_root": str(CAN_RUNTIME_ROOT),
                "blockers": blockers,
            }
        )
    return values


def driver_runtime(name: str) -> str:
    if name not in DRIVERS:
        raise RuntimeError(f"Unknown CAN driver: {name}")
    if DRIVERS[name].requires_dll:
        require_trusted_driver_path(name)
    runtime = require_trusted_runtime_path(name)
    return str(runtime)


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
    selected_dll = require_trusted_driver_path(driver, dll_path)
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
