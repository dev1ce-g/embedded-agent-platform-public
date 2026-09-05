#!/usr/bin/env python3
"""Stable Windows entry point for the embedded-agent Runtime."""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BIN_DIR = Path(__file__).resolve().parent
SOURCE_HOME = BIN_DIR.parent
DEFAULT_INSTALL_ROOT = Path(
    os.environ.get("EMBEDDED_AGENT_INSTALL_ROOT")
    or SOURCE_HOME
).resolve()
DEFAULT_ROOT = DEFAULT_INSTALL_ROOT / "state"
DEFAULT_AGENTCTL = BIN_DIR / "agentctl.py"
SENSITIVE_GLOBAL_OPTIONS = ("--root", "--agentctl", "--sdk-manager")


def failure(message: str, exit_code: int = 127) -> int:
    if exit_code == 2:
        error_code, category, retryable = "INVALID_REQUEST", "invalid_request", False
    else:
        error_code, category, retryable = "CAPABILITY_UNAVAILABLE", "availability", True
    print(
        json.dumps(
            {
                "schema_version": "embedded-capability-result/v1",
                "contract_version": "1.0.0",
                "capability_id": "agent.launcher",
                "phase": "execute",
                "state": "failed",
                "ok": False,
                "operation": "embedded-agent",
                "exit_code": exit_code,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "evidence": [],
                "error": {
                    "code": error_code,
                    "category": category,
                    "message": message,
                    "retryable": retryable,
                },
                "error_code": error_code,
                "first_failure": message,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return exit_code


def decode_payload(value: str) -> list[str]:
    try:
        payload = json.loads(base64.b64decode(value, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid encoded payload: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("args"), list):
        raise ValueError("Encoded payload must contain an args array")
    arguments = [str(item) for item in payload["args"]]
    # Older transports included script, root, and agentctl metadata. They are
    # deliberately ignored: code and mutable state locations are owned by the
    # Windows installation, not by a transport payload.
    return arguments


def _reparse_flag(item_stat: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(item_stat, "st_file_attributes", 0) & flag)


def trusted_python_resource(path: Path, parent: Path, label: str) -> tuple[Path | None, str | None]:
    """Require an exact regular Python file directly inside a trusted directory."""
    try:
        parent_stat = parent.lstat()
        resource_stat = path.lstat()
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return None, f"{label} not found: {path}"
    except OSError as exc:
        return None, f"Cannot inspect {label}: {exc}"
    if parent.is_symlink() or _reparse_flag(parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
        return None, f"{label} directory is not trusted: {parent}"
    if path.is_symlink() or _reparse_flag(resource_stat) or not stat.S_ISREG(resource_stat.st_mode):
        return None, f"{label} must be a regular non-symlink file: {path}"
    if resolved != path or resolved.parent != parent:
        return None, f"{label} escapes its trusted Runtime directory: {path}"
    return resolved, None


def sensitive_global_override(arguments: list[str]) -> str | None:
    """Find a caller option that could override a launcher-owned global."""
    command_seen = False
    for argument in arguments:
        option = argument.split("=", 1)[0]
        if not command_seen and not argument.startswith("-"):
            command_seen = True
            continue
        if command_seen:
            if option in {"--agentctl", "--sdk-manager"}:
                return option
            continue
        if not option.startswith("--") or len(option) <= 2:
            continue
        if any(sensitive.startswith(option) for sensitive in SENSITIVE_GLOBAL_OPTIONS):
            return option
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--payload-b64")
    known, forward = parser.parse_known_args(argv)
    try:
        if known.payload_b64:
            forward = decode_payload(known.payload_b64)
    except ValueError as exc:
        return failure(str(exc), 2)
    root = DEFAULT_ROOT

    override = sensitive_global_override(forward)
    if override:
        return failure(f"Launcher-owned global option cannot be overridden: {override}", 2)

    runtime = SOURCE_HOME / "embedded-agent" / "embedded_agent.py"
    runtime, runtime_failure = trusted_python_resource(runtime, SOURCE_HOME / "embedded-agent", "Agent Runtime")
    if runtime is None:
        return failure(runtime_failure or "Agent Runtime is unavailable")
    agentctl, agentctl_failure = trusted_python_resource(DEFAULT_AGENTCTL, BIN_DIR, "Agent control backend")
    if agentctl is None:
        return failure(agentctl_failure or "Agent control backend is unavailable")

    environment = os.environ.copy()
    environment.pop("EMBEDDED_AGENTCTL", None)
    environment.pop("EMBEDDED_SDK_MANAGER", None)
    environment.update(
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        EMBEDDED_AGENT_INSTALL_ROOT=str(DEFAULT_INSTALL_ROOT),
        EMBEDDED_AGENT_ROOT=str(root),
    )
    command = [sys.executable, str(runtime), "--root", str(root), *forward]
    try:
        completed = subprocess.run(command, env=environment, check=False)
    except OSError as exc:
        return failure(str(exc))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
