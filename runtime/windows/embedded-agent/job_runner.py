#!/usr/bin/env python3
"""Persistent runner for one controlled embedded-agent background job."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "embedded-runtime-job/v1"
REQUEST_SCHEMA_VERSION = "embedded-runtime-job-request/v2"
BUILD_TARGETS = {"keil", "mpu"}
JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
REQUEST_FIELDS = {
    "schema_version",
    "job_id",
    "project_id",
    "background_id",
    "kind",
    "operation_key",
    "parameters",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _bounded_string(value: Any, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"Job request {name} must be a non-empty string of at most {maximum} characters")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"Job request {name} must not contain control characters")
    return value


def _bounded_integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ValueError(f"Job request {name} must be an integer in [{minimum}, {maximum}]")
    return value


def _validate_connection_id(value: Any) -> str:
    connection_id = _bounded_string(value, "parameters.connection_id", 64)
    if not connection_id[0].isalnum() or any(
        not (character.isalnum() or character in "_.-") for character in connection_id
    ):
        raise ValueError("Job request Jenkins connection id contains unsupported characters")
    return connection_id


def _validate_project_id(value: Any) -> str:
    project_id = _bounded_string(value, "project_id", 128)
    stem = project_id.split(".", 1)[0].upper()
    if (
        not PROJECT_ID_PATTERN.fullmatch(project_id)
        or project_id.endswith(".")
        or stem in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("Job request project_id is not canonical")
    return project_id


def _validate_fields(value: dict[str, Any], allowed: set[str], required: set[str], scope: str) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise ValueError(f"Job request {scope} has unsupported fields: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"Job request {scope} is missing fields: {', '.join(missing)}")


def build_controlled_command(
    request: dict[str, Any],
    *,
    root: Path,
) -> list[str]:
    """Validate a typed request and rebuild one allowlisted Runtime command."""
    if not isinstance(request, dict):
        raise ValueError("Job request must be a JSON object")
    if "command" in request:
        raise ValueError("Job request must not contain a command field")
    _validate_fields(request, REQUEST_FIELDS, REQUEST_FIELDS, "object")
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"Job request schema must be {REQUEST_SCHEMA_VERSION}")

    job_id = _bounded_string(request.get("job_id"), "job_id", 128)
    project_id = _validate_project_id(request.get("project_id"))
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("Job request job_id contains unsupported characters")
    _bounded_string(request.get("background_id"), "background_id", 512)
    kind = _bounded_string(request.get("kind"), "kind", 64)
    operation_key = _bounded_string(request.get("operation_key"), "operation_key", 1024)
    parameters = request.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("Job request parameters must be an object")

    runtime_dir = Path(__file__).resolve().parent
    script = runtime_dir / "embedded_agent.py"
    agentctl = runtime_dir.parent / "bin" / "agentctl.py"
    prefix = [
        sys.executable,
        str(script),
        "--root",
        str(Path(root).resolve()),
        "--agentctl",
        str(agentctl),
    ]

    if kind == "build":
        allowed = {"target", "sdk_path"}
        _validate_fields(parameters, allowed, {"target"}, "build parameters")
        target = _bounded_string(parameters.get("target"), "parameters.target", 16)
        if target not in BUILD_TARGETS:
            raise ValueError("Job request build target is not allowlisted")
        expected_key = f"{project_id}:build:{target}"
        if operation_key != expected_key:
            raise ValueError("Job request operation_key does not match build parameters")
        command = [*prefix, "build", "--project", project_id, "--target", target]
        sdk_path = parameters.get("sdk_path")
        if sdk_path is not None:
            command.extend(["--sdk-path", _bounded_string(sdk_path, "parameters.sdk_path")])
        command.append("--json")
        return command

    if kind == "jenkins-wait":
        allowed = {"connection_id", "timeout", "job", "build", "wait_timeout", "poll_interval", "max_chars"}
        _validate_fields(parameters, allowed, allowed, "jenkins-wait parameters")
        connection_id = _validate_connection_id(parameters.get("connection_id"))
        timeout = _bounded_integer(parameters.get("timeout"), "parameters.timeout", 1, 3600)
        jenkins_job = _bounded_string(parameters.get("job"), "parameters.job", 512)
        build = _bounded_integer(parameters.get("build"), "parameters.build", 1, 2147483647)
        wait_timeout = _bounded_integer(parameters.get("wait_timeout"), "parameters.wait_timeout", 1, 86400)
        poll_interval = _bounded_integer(parameters.get("poll_interval"), "parameters.poll_interval", 1, 3600)
        max_chars = _bounded_integer(parameters.get("max_chars"), "parameters.max_chars", 1, 1000000)
        expected_key = f"{project_id}:jenkins-wait:{connection_id}:{jenkins_job}:{build}"
        if operation_key != expected_key:
            raise ValueError("Job request operation_key does not match jenkins-wait parameters")
        return [
            *prefix,
            "jenkins",
            "--connection-id",
            connection_id,
            "--timeout",
            str(timeout),
            "build-wait",
            "--job",
            jenkins_job,
            "--build",
            str(build),
            "--wait-timeout",
            str(wait_timeout),
            "--poll-interval",
            str(poll_interval),
            "--max-chars",
            str(max_chars),
            "--json",
        ]

    raise ValueError(f"Unsupported job kind: {kind}")


def validate_current_background(request: dict[str, Any], root: Path) -> None:
    """Bind a queued Job to the exact project background used at submission."""
    project_id = _validate_project_id(request.get("project_id"))
    requested_background_id = _bounded_string(request.get("background_id"), "background_id", 512)
    background_path = Path(root).resolve() / "projects" / project_id / "background.json"
    try:
        background = read_json(background_path)
    except FileNotFoundError as exc:
        raise ValueError("Project background is missing; submit a new runtime job") from exc
    except OSError as exc:
        raise ValueError(f"Project background cannot be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Project background is not valid JSON; submit a new runtime job") from exc
    if not isinstance(background, dict) or background.get("project_id") != project_id:
        raise ValueError("Project background does not match the queued job project")
    if background.get("background_id") != requested_background_id:
        raise ValueError("Project background changed after this runtime job was queued; submit a new job")


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
        if (
            isinstance(value, dict)
            and isinstance(value.get("ok"), bool)
            and isinstance(value.get("operation"), str)
            and bool(value["operation"])
            and type(value.get("exit_code")) is int
        ):
            return value
    return {
        "ok": False,
        "operation": "runtime-job-child",
        "exit_code": exit_code or 1,
        "first_failure": "Child command did not return valid structured JSON",
    }


def run_job(job_dir: Path) -> int:
    job_dir = job_dir.resolve()
    try:
        request = read_json(job_dir / "request.json")
        if not isinstance(request, dict):
            raise ValueError("Job request must be a JSON object")
        if request.get("job_id") != job_dir.name:
            raise ValueError("Job request job_id does not match its directory")
        root = job_dir.parent.parent
        command = build_controlled_command(
            request,
            root=root,
        )
        validate_current_background(request, root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        update_status(job_dir, state="failed", exit_code=2, finished_at=now_iso(), first_failure=str(exc))
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
        result_exit_code = child_result.get("exit_code")
        child_succeeded = exit_code == 0 and child_result.get("ok") is True and result_exit_code == 0
        state = "canceled" if canceled else "succeeded" if child_succeeded else "failed"
        effective_exit_code = exit_code or (
            result_exit_code if type(result_exit_code) is int and result_exit_code != 0 else (0 if state == "succeeded" else 1)
        )
        update_status(
            job_dir,
            state=state,
            exit_code=130 if canceled else effective_exit_code,
            finished_at=now_iso(),
            cancel_requested=canceled,
            result_path=str(job_dir / "result.json"),
            first_failure=child_result.get("first_failure") if state == "failed" else None,
        )
        return 130 if canceled else effective_exit_code
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
