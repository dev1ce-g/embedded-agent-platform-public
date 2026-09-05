#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from agent_backend_common import *


def default_jlink() -> str:
    configured = os.environ.get("AGENTCTL_JLINK_PATH")
    if configured:
        return configured
    discovered = shutil.which("JLink.exe") or shutil.which("JLink")
    if discovered:
        return discovered
    return str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "SEGGER" / "JLink" / "JLink.exe")


def flash_commands(
    device: str,
    interface: str,
    speed: str,
    address: str,
    binary: Path,
    no_run: bool,
) -> tuple[list[str], dict[str, str]]:
    normalized = {
        "device": jlink_device_token(device),
        "interface": jlink_interface_token(interface),
        "speed": jlink_speed_token(speed),
        "address": jlink_address_token(address, "JLink flash address"),
    }
    binary_token = jlink_script_path(binary, "JLink binary path")
    commands = [
        f"device {normalized['device']}",
        f"si {normalized['interface']}",
        f"speed {normalized['speed']}",
        "connect",
        f"loadbin {binary_token}, {normalized['address']}",
        f"verifybin {binary_token}, {normalized['address']}",
    ]
    if not no_run:
        commands.extend(["r", "g"])
    commands.append("exit")
    return commands, normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Workspace")
    parser.add_argument("-BinPath")
    parser.add_argument("-JLinkPath", default=default_jlink())
    parser.add_argument("-Device", default="S32K312")
    parser.add_argument("-Interface", default="SWD")
    parser.add_argument("-Speed", default="1000")
    parser.add_argument("-Address", default="0x00400000")
    parser.add_argument("-TimeoutSeconds", type=int, default=180)
    parser.add_argument("-Confirm", action="store_true")
    parser.add_argument("-NoRun", action="store_true")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "flash-mcu-jlink"
    started = now_iso()
    log = new_log_path(operation)
    error_log = log.with_suffix(".err.log")
    command_file = log.with_suffix(".cmd")
    if not args.Confirm:
        write_log(log, "Flash gate is closed. Pass -Confirm only after explicit human confirmation.")
        return emit(failure(operation, 3, "Flash gate is closed until a human confirms", log=str(log), requires_human_confirm=True), args.Json)
    jlink = Path(args.JLinkPath)
    if not jlink.is_file():
        return emit(failure(operation, 127, f"JLink not found: {jlink}", log=str(log)), args.Json)
    workspace = Path(args.Workspace) if args.Workspace else None
    binary = Path(args.BinPath) if args.BinPath else (workspace / "mcu" / "project" / "mdk" / "__build" / "bin" / "application.bin" if workspace else None)
    if binary is None or not binary.is_file():
        return emit(failure(operation, 2, f"BIN not found: {binary}", log=str(log), workspace=args.Workspace, bin=str(binary) if binary else None), args.Json)
    binary = binary.resolve()
    try:
        commands, normalized = flash_commands(
            args.Device,
            args.Interface,
            args.Speed,
            args.Address,
            binary,
            args.NoRun,
        )
    except ValueError as exc:
        return emit(failure(operation, 2, str(exc), log=str(log), workspace=args.Workspace), args.Json)
    command_file.write_text("\n".join(commands) + "\n", encoding="utf-8")
    exit_code, _, _ = run_logged([str(jlink), "-CommanderScript", str(command_file)], log, timeout=max(1, args.TimeoutSeconds), error_log=error_log)
    if exit_code == 124:
        return emit(failure(operation, 124, f"JLink flash timed out after {args.TimeoutSeconds} seconds", log=str(log), error_log=str(error_log), command_file=str(command_file), bin=file_info(binary)), args.Json)
    loaded = first_match(log, (r"Downloading file", r"Loading binary file", r"Writing target memory", r"Programming"))
    verified = first_match(log, (r"Verify successful", r"Verification successful", r"Contents already match"))
    failed = first_match(log, (r"Verify failed", r"ERROR:", r"Error:", r"FAILED:", r"Failed", r"Cannot connect", r"Out of sync", r"does not match", r"No J-Link", r"Cannot read"))
    failed = failed or first_match(error_log, (r"Error:", r"Cannot", r"Failed"))
    ok = exit_code == 0 and bool(loaded) and bool(verified) and not failed
    if not ok and exit_code == 0:
        exit_code = 1
    return emit(result(ok, operation, exit_code, workspace=args.Workspace, **normalized, started_at=started, ended_at=now_iso(), jlink=str(jlink), log=str(log), error_log=str(error_log), command_file=str(command_file), load_marker=loaded, verify_marker=verified, first_failure=failed or (None if ok else "Missing JLink programming evidence"), bin=file_info(binary)), args.Json)


if __name__ == "__main__":
    raise SystemExit(main())
