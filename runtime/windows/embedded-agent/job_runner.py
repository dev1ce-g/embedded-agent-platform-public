#!/usr/bin/env python3
"""Persistent runner for one controlled embedded-agent background job."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "embedded-runtime-job/v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def update_status(job_dir: Path, **fields: Any) -> dict[str, Any]:
    status_path = job_dir / "status.json"
    try:
        status = read_json(status_path)
    except (OSError, json.JSONDecodeError):
        status = {"schema_version": SCHEMA_VERSION, "job_id": job_dir.name}
    status.update(fields)
    write_json_atomic(status_path, status)
    return status


def terminate_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def parse_child_result(path: Path, exit_code: int) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        raw = b""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {
        "ok": exit_code == 0,
        "operation": "runtime-job-child",
        "exit_code": exit_code,
        "first_failure": None if exit_code == 0 else "Child command did not return structured JSON",
    }


def run_job(job_dir: Path) -> int:
    request = read_json(job_dir / "request.json")
    command = request.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        update_status(job_dir, state="failed", exit_code=2, finished_at=now_iso(), first_failure="Invalid controlled command")
        return 2
    if (job_dir / "cancel.requested").exists():
        update_status(job_dir, state="canceled", exit_code=130, finished_at=now_iso(), cancel_requested=True)
        return 130

    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    process: subprocess.Popen[bytes] | None = None
    canceled = False
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                close_fds=True,
                creationflags=creationflags,
            )
            update_status(
                job_dir,
                state="running",
                runner_pid=os.getpid(),
                child_pid=process.pid,
                started_at=now_iso(),
            )
            while process.poll() is None:
                if (job_dir / "cancel.requested").exists():
                    canceled = True
                    terminate_child(process)
                    break
                time.sleep(0.25)
            exit_code = process.wait()
        child_result = parse_child_result(stdout_path, exit_code)
        write_json_atomic(job_dir / "result.json", child_result)
        state = "canceled" if canceled else "succeeded" if exit_code == 0 and child_result.get("ok") is not False else "failed"
        update_status(
            job_dir,
            state=state,
            exit_code=130 if canceled else exit_code,
            finished_at=now_iso(),
            cancel_requested=canceled,
            result_path=str(job_dir / "result.json"),
            first_failure=child_result.get("first_failure") if state == "failed" else None,
        )
        return 130 if canceled else exit_code
    except Exception as exc:
        if process is not None:
            terminate_child(process)
        update_status(job_dir, state="failed", exit_code=127, finished_at=now_iso(), first_failure=str(exc))
        return 127


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    args = parser.parse_args(argv or sys.argv[1:])
    return run_job(args.job_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
