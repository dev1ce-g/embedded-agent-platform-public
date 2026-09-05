#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from agent_backend_common import *


def first_existing(candidates: list[Path | str | None]) -> Path | None:
    return next((Path(item) for item in candidates if item and Path(item).is_file()), None)


def map_symbol_address(path: Path, symbol: str) -> dict[str, str] | None:
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    for line in lines:
        match = re.match(r"^\s*_SEGGER_RTT\s+(0x[0-9A-Fa-f]+)\s+Data\b", line)
        if symbol in line and match:
            return {"address": match.group(1), "line": line}
    for line in lines:
        if symbol not in line:
            continue
        values = re.findall(r"0x[0-9A-Fa-f]+|[0-9A-Fa-f]{8,}", line)
        for value in values:
            normalized = value if value.lower().startswith("0x") else f"0x{value}"
            if normalized.lower() == "0x00000000":
                continue
            if re.fullmatch(r"0x20[0-9A-Fa-f]{6}|0x204[0-9A-Fa-f]{5}", normalized):
                return {"address": normalized, "line": line}
    return None


def find_rtt_symbol(mdk: Path, axf: Path, fromelf: Path, run_dir: Path) -> dict[str, Any]:
    maps = [mdk / "Objects" / "application.map", mdk / "Listings" / "application.map"]
    maps.extend(sorted(mdk.rglob("*.map"), key=lambda item: item.stat().st_mtime, reverse=True)[:1])
    seen: set[Path] = set()
    for path in maps:
        if path in seen:
            continue
        seen.add(path)
        found = map_symbol_address(path, "_SEGGER_RTT")
        if found:
            return {"ok": True, "source": "map", "path": str(path), **found}
    symbol_log = run_dir / "fromelf-symbols.txt"
    code, output, error = run_logged([str(fromelf), "--text", "-s", str(axf)], symbol_log)
    for line in (output + "\n" + error).splitlines():
        if "_SEGGER_RTT" in line:
            match = re.search(r"0x[0-9A-Fa-f]+", line)
            if match:
                return {"ok": code == 0, "source": "fromelf", "address": match.group(0), "line": line, "path": str(symbol_log)}
    return {"ok": False, "source": "not-found", "path": str(symbol_log)}


def parse_control_block(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = path.read_bytes()
    if len(data) < 0x2C:
        return None
    magic = data[:16].split(b"\0", 1)[0].decode("ascii", errors="replace")
    if not magic.startswith("SEGGER RTT"):
        return {"valid": False, "magic": magic, "first_failure": "RTT control block magic is invalid"}
    address, size, write_offset, read_offset = struct.unpack_from("<IIII", data, 0x1C)
    valid = address != 0 and 0 < size <= 1024 * 1024 and write_offset < size and read_offset < size
    return {
        "valid": valid,
        "magic": magic,
        "buffer_address": f"0x{address:08X}",
        "buffer_size": size,
        "write_offset": write_offset,
        "read_offset": read_offset,
        "first_failure": None if valid else "RTT buffer descriptor is invalid",
    }


def rtt_bytes(buffer: bytes, write_offset: int, read_offset: int) -> bytes:
    if not buffer or write_offset > len(buffer) or read_offset > len(buffer):
        return b""
    if write_offset > read_offset:
        return buffer[read_offset:write_offset]
    if write_offset < read_offset:
        return buffer[read_offset:] + buffer[:write_offset]
    return b""


def rtt_text(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text).replace("\0", "")
    return "".join(character for character in text if character in "\t\n\r" or 0x20 <= ord(character) <= 0x7E).strip()


def write_jlink_script(path: Path, chip: str, wait_ms: int, reset: bool, rtt_address: str, cb_path: Path, buffer_address: str | None = None, buffer_size: int = 0, buffer_path: Path | None = None) -> None:
    device_token = jlink_device_token(chip)
    wait_token = jlink_size_token(wait_ms, "JLink sleep duration", 60000)
    rtt_address_token = jlink_address_token(rtt_address, "RTT control block address")
    if int(rtt_address_token, 16) == 0:
        raise ValueError("RTT control block address cannot be zero")
    cb_path_token = jlink_script_path(cb_path, "RTT control block output path")
    lines = [f"Device {device_token}", "Si SWD", "Speed 4000", "Connect"]
    if reset:
        lines.append("r")
    lines.extend(["g", f"Sleep {wait_token}", "h", f"SaveBin {cb_path_token} {rtt_address_token} 0xA8"])
    if buffer_address and buffer_size > 0 and buffer_path:
        buffer_address_token = jlink_address_token(buffer_address, "RTT buffer address")
        if int(buffer_address_token, 16) == 0:
            raise ValueError("RTT buffer address cannot be zero")
        buffer_size_token = jlink_size_token(buffer_size, "RTT buffer size", 1024 * 1024)
        buffer_path_token = jlink_script_path(buffer_path, "RTT buffer output path")
        lines.append(f"SaveBin {buffer_path_token} {buffer_address_token} {buffer_size_token}")
    lines.extend([f"mem32 {rtt_address_token}, 0x10", "q"])
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Workspace")
    parser.add_argument("-WaitMs", type=int, default=12000)
    parser.add_argument("-Uv4Path", default=os.environ.get("AGENTCTL_UV4_PATH"))
    parser.add_argument("-JLinkPath", default=os.environ.get("AGENTCTL_JLINK_PATH"))
    parser.add_argument("-FromElfPath", default=os.environ.get("AGENTCTL_FROMELF_PATH"))
    parser.add_argument("-Reset", action="store_true")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "rtt-capture-mcu"
    started = now_iso()
    log = new_log_path(operation)
    run_dir = AGENT_HOME / "artifacts" / f"rtt-mcu-{datetime.now():%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    wait_ms = min(60000, max(1000, args.WaitMs))
    workspace = Path(args.Workspace) if args.Workspace else None
    if workspace is None or not workspace.is_dir():
        return emit(failure(operation, 2, "Workspace not found", log=str(log), workspace=args.Workspace), args.Json)
    mdk = workspace / "mcu" / "project" / "mdk"
    project = mdk / "application.uvprojx"
    if not project.is_file():
        return emit(failure(operation, 2, f"MDK project not found: {project}", log=str(log), workspace=str(workspace)), args.Json)
    uv4 = first_existing([args.Uv4Path, r"C:\Keil_v5\UV4\UV4.exe"])
    keil_root = uv4.parent.parent if uv4 else None
    jlink = first_existing([args.JLinkPath, keil_root / "ARM" / "Segger" / "JLink.exe" if keil_root else None, r"C:\Program Files\SEGGER\JLink\JLink.exe"])
    fromelf = first_existing([args.FromElfPath, keil_root / "ARM" / "ARMCLANG" / "bin" / "fromelf.exe" if keil_root else None, keil_root / "ARM" / "ARMCC" / "bin" / "fromelf.exe" if keil_root else None])
    for name, tool in (("UV4", uv4), ("JLink", jlink), ("fromelf", fromelf)):
        if tool is None:
            return emit(failure(operation, 127, f"{name} not found", log=str(log), workspace=str(workspace)), args.Json)
    assert uv4 and jlink and fromelf

    try:
        root = ET.parse(project).getroot()
    except (OSError, ET.ParseError) as exc:
        return emit(failure(operation, 2, f"Invalid MDK project XML: {exc}", log=str(log)), args.Json)
    device = next((node.text or "" for node in root.iter() if node.tag.endswith("Device")), "")
    try:
        device = strict_single_line(device, "Keil Device", 256)
        chip = jlink_device_token(device.split(":", 1)[0])
    except ValueError as exc:
        return emit(failure(operation, 2, str(exc), log=str(log)), args.Json)
    output_name = next((node.text or "" for node in root.iter() if node.tag.endswith("OutputName")), "application") or "application"
    output_directory = next((node.text or "" for node in root.iter() if node.tag.endswith("OutputDirectory")), ".\\Objects\\") or ".\\Objects\\"
    output_dir = Path(output_directory)
    if not output_dir.is_absolute():
        output_dir = mdk / output_dir
    axf = output_dir / f"{output_name}.axf"
    if not axf.is_file():
        axf = mdk / "Objects" / "application.axf"
    if not axf.is_file():
        return emit(failure(operation, 2, f"AXF not found: {axf}", log=str(log)), args.Json)
    symbol = find_rtt_symbol(mdk, axf, fromelf, run_dir)
    if not symbol["ok"]:
        return emit(failure(operation, 4, "RTT symbol _SEGGER_RTT not found", log=str(log), symbol_log=symbol["path"]), args.Json)
    try:
        address = jlink_address_token(symbol["address"], "RTT symbol address")
        if int(address, 16) == 0:
            raise ValueError("RTT symbol address cannot be zero")
    except (TypeError, ValueError) as exc:
        return emit(failure(operation, 4, str(exc), log=str(log), symbol_log=symbol["path"]), args.Json)

    probe_script, probe_cb, probe_log = run_dir / "jlink-rtt-probe.jlink", run_dir / "rtt-cb-probe.bin", run_dir / "jlink-rtt-probe.log"
    try:
        write_jlink_script(probe_script, chip, 2000, args.Reset, address, probe_cb)
    except ValueError as exc:
        return emit(failure(operation, 2, str(exc), log=str(log)), args.Json)
    run_logged([str(jlink), "-CommandFile", str(probe_script)], probe_log)
    probe = parse_control_block(probe_cb)
    if not probe or not probe["valid"]:
        return emit(failure(operation, 5, probe["first_failure"] if probe else "RTT control block was not captured", log=str(log), jlink_log=str(probe_log), rtt_address=address), args.Json)

    capture_script, capture_cb = run_dir / "jlink-rtt-capture.jlink", run_dir / "rtt-cb.bin"
    buffer_path, jlink_log = run_dir / "rtt-buffer.bin", run_dir / "jlink-rtt-capture.log"
    try:
        write_jlink_script(capture_script, chip, wait_ms, args.Reset, address, capture_cb, probe["buffer_address"], probe["buffer_size"], buffer_path)
    except ValueError as exc:
        return emit(failure(operation, 2, str(exc), log=str(log)), args.Json)
    run_logged([str(jlink), "-CommandFile", str(capture_script)], jlink_log)
    capture = parse_control_block(capture_cb)
    if not capture or not capture["valid"]:
        return emit(failure(operation, 5, capture["first_failure"] if capture else "RTT control block was not captured", log=str(log), jlink_log=str(jlink_log), rtt_address=address), args.Json)
    buffer = buffer_path.read_bytes()
    text = rtt_text(rtt_bytes(buffer, capture["write_offset"], capture["read_offset"]))
    mode = "ring"
    if not text and capture["write_offset"] == capture["read_offset"]:
        text, mode = rtt_text(buffer), "snapshot"
    text_path = run_dir / "rtt.txt"
    text_path.write_text(text, encoding="utf-8")
    write_log(log, jlink_log.read_bytes())
    lines = [line for line in text.splitlines() if line]
    ok = bool(text)
    exit_code = 0 if ok else 6
    return emit(
        result(ok, operation, exit_code, workspace=str(workspace), started_at=started, ended_at=now_iso(), log=str(log), text_log=str(text_path), jlink_log=str(jlink_log), symbol_log=symbol["path"], artifact_dir=str(run_dir), first_failure=None if ok else "RTT capture produced no printable text", capture={"mode": mode, "wait_ms": wait_ms, "reset": args.Reset, "text_size": len(text), "line_count": len(lines), "first_lines": lines[:30], "last_lines": lines[-30:]}, rtt={"device": device, "chip": chip, "axf": str(axf), "symbol_source": symbol["source"], "symbol_path": symbol["path"], "symbol_line": symbol.get("line"), "rtt_address": address, "buffer_address": capture["buffer_address"], "buffer_size": capture["buffer_size"], "write_offset": capture["write_offset"], "read_offset": capture["read_offset"]}, tools={"jlink": str(jlink), "fromelf": str(fromelf), "uv4": str(uv4)}),
        args.Json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
