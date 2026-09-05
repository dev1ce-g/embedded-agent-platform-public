#!/usr/bin/env python3
"""ControlCAN DLL discovery and bounded device probes."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
from pathlib import Path
from typing import Any

from can_middleware import DRIVER_CONFIG_PATH, DriverTrustError, require_trusted_driver_path

DEFAULT_TYPES = (3, 4, 20, 21, 31, 34, 17, 32, 36, 37, 47)


class InitConfig(ctypes.Structure):
    _fields_ = [
        ("AccCode", ctypes.c_uint32),
        ("AccMask", ctypes.c_uint32),
        ("Reserved", ctypes.c_uint32),
        ("Filter", ctypes.c_ubyte),
        ("Timing0", ctypes.c_ubyte),
        ("Timing1", ctypes.c_ubyte),
        ("Mode", ctypes.c_ubyte),
    ]


def pe_machine(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0x3C)
            pe_offset = struct.unpack("<I", handle.read(4))[0]
            handle.seek(pe_offset + 4)
            machine = struct.unpack("<H", handle.read(2))[0]
        return {0x014C: "x86", 0x8664: "x64"}.get(machine, f"0x{machine:04X}")
    except (OSError, struct.error):
        return "unknown"


def configure(dll: Any) -> None:
    dll.VCI_OpenDevice.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    dll.VCI_OpenDevice.restype = ctypes.c_uint32
    dll.VCI_CloseDevice.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    dll.VCI_CloseDevice.restype = ctypes.c_uint32
    if hasattr(dll, "VCI_InitCAN"):
        dll.VCI_InitCAN.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(InitConfig)]
        dll.VCI_InitCAN.restype = ctypes.c_uint32
        dll.VCI_StartCAN.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        dll.VCI_StartCAN.restype = ctypes.c_uint32
        dll.VCI_ResetCAN.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        dll.VCI_ResetCAN.restype = ctypes.c_uint32


def probe(path: Path, device_types: list[int], indexes: list[int], try_init: bool, can_index: int) -> list[dict[str, Any]]:
    trusted = require_trusted_driver_path("controlcan", path)
    assert trusted is not None
    path = trusted
    required = pe_machine(path)
    actual = "x86" if struct.calcsize("P") == 4 else "x64"
    if required in {"x86", "x64"} and required != actual:
        return [{"dll": str(path), "error": f"DLL is {required}; run this adapter with {required} Python", "process_arch": actual}]
    results: list[dict[str, Any]] = []
    directories = [path.parent, path.parent / "kerneldlls", path.parent / "plugin", path.parent.parent, path.parent.parent / "kerneldlls", path.parent.parent / "plugin"]
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(str(item) for item in directories if item.is_dir()) + os.pathsep + old_path
    handles = []
    dll = None
    try:
        if hasattr(os, "add_dll_directory"):
            handles = [os.add_dll_directory(str(item)) for item in directories if item.is_dir()]
        loader = getattr(ctypes, "WinDLL", ctypes.CDLL)
        dll = loader(str(path))
        configure(dll)
        for device_type in device_types:
            for index in indexes:
                item: dict[str, Any] = {"dll": str(path), "type": device_type, "index": index}
                try:
                    opened = int(dll.VCI_OpenDevice(device_type, index, 0))
                    item["open"] = opened
                    if opened == 1 and try_init:
                        config = InitConfig(0, 0xFFFFFFFF, 0, 1, 0, 0x1C, 0)
                        item["init"] = int(dll.VCI_InitCAN(device_type, index, can_index, ctypes.byref(config)))
                        if item["init"] == 1:
                            item["start"] = int(dll.VCI_StartCAN(device_type, index, can_index))
                            dll.VCI_ResetCAN(device_type, index, can_index)
                    if opened == 1:
                        dll.VCI_CloseDevice(device_type, index)
                except (OSError, ValueError) as exc:
                    item["error"] = str(exc)
                results.append(item)
    except OSError as exc:
        results.append({"dll": str(path), "error": str(exc), "process_arch": actual})
    finally:
        if dll is not None and hasattr(ctypes, "windll"):
            ctypes.windll.kernel32.FreeLibrary(ctypes.c_void_p(dll._handle))
        for handle in handles:
            handle.close()
        os.environ["PATH"] = old_path
    return results


def csv_integers(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("discover", "one", "range"), nargs="?", default="discover")
    parser.add_argument("-Dll", action="append", default=[])
    parser.add_argument("-DevTypes", default=",".join(map(str, DEFAULT_TYPES)))
    parser.add_argument("-DevIndexes", default="0,1,2")
    parser.add_argument("-TryInit", action="store_true")
    parser.add_argument("-CanIndex", type=int, default=0)
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    requested = args.Dll[0] if len(args.Dll) == 1 else None
    try:
        if len(args.Dll) > 1:
            raise DriverTrustError("ControlCAN accepts exactly one machine-configured DLL")
        trusted = require_trusted_driver_path("controlcan", requested)
        assert trusted is not None
    except DriverTrustError as exc:
        value = {
            "ok": False,
            "operation": "probe-controlcan",
            "exit_code": 2,
            "mode": args.mode,
            "driver_config": str(DRIVER_CONFIG_PATH),
            "inventory": [],
            "results": [],
            "first_failure": str(exc),
        }
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":") if args.Json else None, indent=None if args.Json else 2))
        return 2
    paths = [trusted]
    types = list(range(1, 101)) if args.mode == "range" else csv_integers(args.DevTypes)
    indexes = list(range(8)) if args.mode == "range" else csv_integers(args.DevIndexes)
    inventory = [{"path": str(path), "exists": path.is_file(), "arch": pe_machine(path) if path.is_file() else None} for path in paths]
    results: list[dict[str, Any]] = []
    for path in paths:
        if path.is_file():
            results.extend(probe(path, types, indexes, args.TryInit, args.CanIndex))
    probe_ok = bool(results) and not any("error" in item for item in results)
    first_failure = next((str(item["error"]) for item in results if "error" in item), None)
    value = {"ok": probe_ok, "operation": "probe-controlcan", "exit_code": 0 if probe_ok else 1 if results else 2, "mode": args.mode, "process_arch": "x86" if struct.calcsize("P") == 4 else "x64", "inventory": inventory, "results": results, "first_failure": first_failure}
    if args.mode == "range":
        value["results"] = [item for item in results if item.get("open") not in {0, None} or "error" in item]
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":") if args.Json else None, indent=None if args.Json else 2))
    return int(value["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
