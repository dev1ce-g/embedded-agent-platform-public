"""Bounded read-only Windows process diagnostics."""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
from typing import Any

from embedded_runtime_common import decode_text, print_result, result


PROCESS_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,80}\.exe\Z", re.IGNORECASE)


def parse_tasklist_csv(text: str) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[0].startswith("INFO:"):
            continue
        try:
            pid = int(row[1])
        except ValueError:
            continue
        processes.append({"image_name": row[0], "pid": pid})
    return processes


def command_diagnose(args: argparse.Namespace) -> int:
    operation = f"diagnose-{args.diagnose_action}"
    if not PROCESS_NAME_PATTERN.fullmatch(args.name):
        value = result(False, operation, 2, first_failure="Process name must be a bounded .exe image name")
        print_result(value, args.json)
        return 2
    command = ["tasklist.exe", "/FI", f"IMAGENAME eq {args.name}", "/FO", "CSV", "/NH"]
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        value = result(False, operation, 127, name=args.name, first_failure=str(exc))
        print_result(value, args.json)
        return 127
    stdout, _, binary = decode_text(completed.stdout or b"")
    if binary or stdout is None:
        stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    processes = parse_tasklist_csv(stdout)
    if args.diagnose_action == "process-stop":
        if not args.require_confirm or not args.confirm:
            value = result(
                False,
                operation,
                3,
                name=args.name,
                pid=args.pid,
                blocked=True,
                requires_human_confirm=True,
                first_failure="Process stop requires --require-confirm --confirm",
            )
            print_result(value, args.json)
            return 3
        matched = next((item for item in processes if item["pid"] == args.pid and item["image_name"].lower() == args.name.lower()), None)
        if matched is None:
            value = result(False, operation, 4, name=args.name, pid=args.pid, first_failure="PID and image name did not match a running process")
            print_result(value, args.json)
            return 4
        stop_command = ["taskkill.exe", "/PID", str(args.pid), "/T", "/F"]
        try:
            stopped = subprocess.run(stop_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            value = result(False, operation, 127, name=args.name, pid=args.pid, first_failure=str(exc))
            print_result(value, args.json)
            return 127
        value = result(
            stopped.returncode == 0,
            operation,
            stopped.returncode,
            name=args.name,
            pid=args.pid,
            stopped=matched,
            gate={"level": "L3", "requires_human_confirm": True, "confirmed": True},
            first_failure=None if stopped.returncode == 0 else "taskkill.exe failed",
        )
        print_result(value, args.json)
        return stopped.returncode
    value = result(
        completed.returncode == 0,
        operation,
        completed.returncode,
        name=args.name,
        count=len(processes),
        processes=processes,
        read_only=True,
        first_failure=None if completed.returncode == 0 else "tasklist.exe failed",
    )
    print_result(value, args.json)
    return completed.returncode
