#!/usr/bin/env python3
"""Bounded ZCANPro zlgcan.dll device discovery without channel initialization."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
from pathlib import Path
from typing import Any

from zcanpro_dll import ZCanDeviceInfo, _valid_handle, bind_library, load_library


DEFAULT_DLL = os.environ.get("EMBEDDED_ZCANPRO_DLL") or str(
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ZCANPRO" / "zlgcan.dll"
)
DEFAULT_TYPES = (3, 4, 20, 21, 31, 34, 38, 39, 40, 41, 42, 43, 59, 60, 61, 62, 63, 76, 82, 83, 84, 85)


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


def csv_integers(value: str) -> list[int]:
    return [int(item.strip(), 0) for item in value.split(",") if item.strip()]


def probe(path: Path, device_types: list[int], indexes: list[int]) -> list[dict[str, Any]]:
    required = pe_machine(path)
    actual = "x86" if struct.calcsize("P") == 4 else "x64"
    if required in {"x86", "x64"} and required != actual:
        return [{"dll": str(path), "error": f"DLL is {required}; run this adapter with {required} Python", "process_arch": actual}]
    handles: list[Any] = []
    dll = None
    results: list[dict[str, Any]] = []
    try:
        dll, handles = load_library(str(path))
        bind_library(dll)
        for device_type in device_types:
            for index in indexes:
                item: dict[str, Any] = {"dll": str(path), "type": device_type, "index": index}
                device_handle = None
                try:
                    device_handle = dll.ZCAN_OpenDevice(device_type, index, 0)
                    item["open"] = 1 if _valid_handle(device_handle) else 0
                    if item["open"] == 1:
                        if hasattr(dll, "ZCAN_GetDeviceInf"):
                            info = ZCanDeviceInfo()
                            item["device_info"] = int(dll.ZCAN_GetDeviceInf(device_handle, ctypes.byref(info)))
                            if item["device_info"] == 1:
                                item["serial_number"] = bytes(info.serial_number).split(b"\0", 1)[0].decode("ascii", "replace")
                                item["hardware_type"] = bytes(info.hardware_type).split(b"\0", 1)[0].decode("ascii", "replace")
                                item["can_channels"] = int(info.can_channels)
                                item["physical"] = bool(item["serial_number"] or item["hardware_type"])
                except (OSError, ValueError) as exc:
                    item["error"] = str(exc)
                finally:
                    if _valid_handle(device_handle):
                        try:
                            item["close"] = int(dll.ZCAN_CloseDevice(device_handle))
                        except (OSError, ValueError) as exc:
                            item.setdefault("error", f"ZCAN_CloseDevice failed: {exc}")
                results.append(item)
    except (AttributeError, OSError) as exc:
        results.append({"dll": str(path), "error": str(exc), "process_arch": actual})
    finally:
        for handle in handles:
            handle.close()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("discover",), nargs="?", default="discover")
    parser.add_argument("-Dll", default=DEFAULT_DLL)
    parser.add_argument("-DevTypes", default=",".join(map(str, DEFAULT_TYPES)))
    parser.add_argument("-DevIndexes", default="0,1,2")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.Dll)
    inventory = [{"path": str(path), "exists": path.is_file(), "arch": pe_machine(path) if path.is_file() else None}]
    results = probe(path, csv_integers(args.DevTypes), csv_integers(args.DevIndexes)) if path.is_file() else []
    probe_ok = bool(results) and not any("error" in item for item in results)
    first_failure = next((str(item["error"]) for item in results if "error" in item), None)
    if not path.is_file():
        first_failure = f"ZCANPro DLL not found: {path}"
    value = {
        "ok": probe_ok,
        "operation": "probe-zcanpro",
        "exit_code": 0 if probe_ok else 1 if results else 2,
        "mode": args.mode,
        "process_arch": "x86" if struct.calcsize("P") == 4 else "x64",
        "inventory": inventory,
        "results": results,
        "first_failure": first_failure,
    }
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":") if args.Json else None, indent=None if args.Json else 2))
    return int(value["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
