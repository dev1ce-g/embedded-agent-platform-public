#!/usr/bin/env python3
"""Stable Windows entry point for the embedded-agent Runtime."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path


BIN_DIR = Path(__file__).resolve().parent
SOURCE_HOME = BIN_DIR.parent
DEFAULT_INSTALL_ROOT = Path(
    os.environ.get("EMBEDDED_AGENT_INSTALL_ROOT")
    or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EmbeddedAgentPlatform"
)
DEFAULT_ROOT = DEFAULT_INSTALL_ROOT / "state"
DEFAULT_AGENTCTL = BIN_DIR / "agentctl.py"


def failure(message: str) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "operation": "embedded-agent",
                "exit_code": 127,
                "first_failure": message,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 127


def decode_payload(value: str) -> tuple[Path, Path, Path, list[str]]:
    try:
        payload = json.loads(base64.b64decode(value, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid encoded payload: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("args"), list):
        raise ValueError("Encoded payload must contain an args array")
    script = Path(str(payload.get("script") or BIN_DIR / "embedded-agent.py"))
    root = Path(str(payload.get("root") or DEFAULT_ROOT))
    agentctl = Path(str(payload.get("agentctl") or DEFAULT_AGENTCTL))
    arguments = [str(item) for item in payload["args"]]
    return script, root, agentctl, arguments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--payload-b64")
    known, forward = parser.parse_known_args(argv)
    try:
        if known.payload_b64:
            _, root, agentctl, forward = decode_payload(known.payload_b64)
        else:
            root = Path(os.environ.get("EMBEDDED_AGENT_ROOT", str(DEFAULT_ROOT)))
            agentctl = Path(os.environ.get("EMBEDDED_AGENTCTL", str(DEFAULT_AGENTCTL)))
    except ValueError as exc:
        return failure(str(exc))

    runtime = SOURCE_HOME / "embedded-agent" / "embedded_agent.py"
    if not runtime.is_file():
        return failure(f"Agent script not found: {runtime}")
    if not agentctl.is_file():
        return failure(f"Agent backend not found: {agentctl}")

    environment = os.environ.copy()
    environment.update(
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        EMBEDDED_AGENT_ROOT=str(root),
        EMBEDDED_AGENTCTL=str(agentctl),
    )
    command = [sys.executable, str(runtime), "--root", str(root), "--agentctl", str(agentctl), *forward]
    try:
        completed = subprocess.run(command, env=environment, check=False)
    except OSError as exc:
        return failure(str(exc))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
