#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from agent_backend_common import *


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    default_jlink = os.environ.get("AGENTCTL_JLINK_PATH") or shutil.which("JLink.exe") or str(
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "SEGGER" / "JLink" / "JLink.exe"
    )
    parser.add_argument("-JLinkPath", default=default_jlink)
    parser.add_argument("-Device", default="S32K312")
    parser.add_argument("-Interface", default="SWD")
    parser.add_argument("-Speed", default="1000")
    parser.add_argument("-TimeoutSeconds", type=int, default=30)
    parser.add_argument("-Halt", action="store_true")
    parser.add_argument("-ResetBeforeHalt", action="store_true")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "jlink-probe"
    started = now_iso()
    log = new_log_path(operation)
    error_log = log.with_suffix(".err.log")
    command_file = log.with_suffix(".cmd")
    jlink = Path(args.JLinkPath)
    if not jlink.is_file():
        write_log(log, f"JLink not found: {jlink}")
        return emit(failure(operation, 127, f"JLink not found: {jlink}", log=str(log)), args.Json)

    commands = [f"device {args.Device}", f"si {args.Interface}", f"speed {args.Speed}", "connect"]
    if args.ResetBeforeHalt:
        commands.append("r")
    if args.Halt or args.ResetBeforeHalt:
        commands.append("h")
    commands.extend(["mem32 0xE000ED00 1", "exit"])
    command_file.write_text("\n".join(commands) + "\n", encoding="ascii")
    exit_code, _, _ = run_logged(
        [str(jlink), "-CommanderScript", str(command_file)],
        log,
        timeout=max(1, args.TimeoutSeconds),
        error_log=error_log,
    )
    if exit_code == 124:
        return emit(failure(operation, 124, f"JLink probe timed out after {args.TimeoutSeconds} seconds", log=str(log), error_log=str(error_log), command_file=str(command_file)), args.Json)
    success = first_match(log, (r"Cortex-M", r"CPUID", r"E000ED00", r"Connected", r"Found SW-DP"))
    halt = first_match(log, (r"CPU halted", r"Core halted", r"PC =", r"R0 ="))
    failed = first_match(log, (r"Cannot connect", r"Failed to connect", r"Unknown SDA AP Id", r"Failed to halt", r"could not be halted", r"Error:", r"Cannot read", r"No J-Link"))
    failed = failed or first_match(error_log, (r"Error:", r"Cannot", r"Failed"))
    ok = exit_code == 0 and bool(success) and not failed
    if not ok and exit_code == 0:
        exit_code = 1
    return emit(result(ok, operation, exit_code, device=args.Device, interface=args.Interface, speed=args.Speed, halt_requested=args.Halt or args.ResetBeforeHalt, reset_before_halt=args.ResetBeforeHalt, started_at=started, ended_at=now_iso(), log=str(log), error_log=str(error_log), command_file=str(command_file), success_marker=success, halt_marker=halt, first_failure=failed or (None if ok else "Missing JLink connection evidence")), args.Json)


if __name__ == "__main__":
    raise SystemExit(main())
