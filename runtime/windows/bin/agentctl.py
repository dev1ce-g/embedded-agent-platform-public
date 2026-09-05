#!/usr/bin/env python3
"""Python dispatcher for Windows embedded-agent backends.

Runtime policy, gates, JSON evidence and platform adapters all execute through
Python.  This module deliberately has no secondary shell fallback.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


BIN_DIR = Path(__file__).resolve().parent
SOURCE_HOME = BIN_DIR.parent
AGENT_HOME = Path(os.environ.get("EMBEDDED_AGENT_HOME", str(SOURCE_HOME))).resolve()
RUNTIME_DIR = SOURCE_HOME / "embedded-agent"
sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_common import decode_text, iter_tool_files, result, sha256_file  # noqa: E402


LOG_DIR = AGENT_HOME / "logs"


def option(arguments: list[str], name: str, default: str | None = None) -> str | None:
    try:
        index = arguments.index(name)
    except ValueError:
        return default
    return arguments[index + 1] if index + 1 < len(arguments) else default


def flag(arguments: list[str], name: str) -> bool:
    return name in arguments


def emit(value: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    return int(value.get("exit_code", 0 if value.get("ok") else 1))


def failure(operation: str, exit_code: int, message: str, **fields: Any) -> dict[str, Any]:
    return result(False, operation, exit_code, first_failure=message, **fields)


def run_adapter(script_name: str, parameters: list[str], as_json: bool) -> int:
    script = BIN_DIR / script_name
    if not script.is_file():
        return emit(failure(script_name, 127, f"Adapter not found: {script}"), as_json)
    if script.suffix.lower() != ".py":
        return emit(failure(script_name, 126, f"Adapter must be Python: {script}"), as_json)
    command = [sys.executable, str(script), *parameters]
    if as_json:
        command.append("-Json")
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        return emit(failure(script_name, 127, str(exc), backend_command=command), as_json)
    stdout, _, stdout_binary = decode_text(completed.stdout or b"")
    stderr, _, stderr_binary = decode_text(completed.stderr or b"")
    if stdout_binary or stdout is None:
        stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    if stderr_binary or stderr is None:
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    if stdout:
        print(stdout.rstrip())
    if stderr:
        print(stderr.rstrip(), file=sys.stderr)
    if not stdout and completed.returncode != 0:
        return emit(
            failure(script_name, completed.returncode, stderr.strip() or "Adapter returned no structured result", backend_command=command),
            as_json,
        )
    return completed.returncode


def latest_artifact(workspace: Path) -> dict[str, Any] | None:
    artifact_suffixes = {".pac", ".zip", ".bin", ".hex", ".elf", ".axf"}
    candidates = [
        item for item in iter_tool_files(workspace)
        if item.suffix.lower() in artifact_suffixes
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    stat = latest.stat()
    return {
        "path": str(latest),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": sha256_file(latest),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv or sys.argv[1:])
    as_json = flag(arguments, "--json")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not arguments:
        return emit(failure("agentctl", 2, "Missing subcommand"), as_json)
    command = arguments[0]

    if command == "status":
        return emit(
            result(
                True,
                "status",
                agent_root=str(AGENT_HOME),
                logs=str(LOG_DIR),
                python=sys.version.split()[0],
                dispatcher="python",
            ),
            as_json,
        )
    if command == "build":
        if len(arguments) < 2 or arguments[1] not in {"mcu", "mpu"}:
            return emit(failure("build", 2, "Missing or unknown build target"), as_json)
        parameters: list[str] = []
        for source, target in (("--workspace", "-Workspace"), ("--artifact-root", "-ArtifactRoot"), ("--container", "-Container")):
            value = option(arguments, source)
            if value:
                parameters.extend([target, value])
        if arguments[1] == "mcu":
            project_path = option(arguments, "--project-path")
            if not project_path:
                return emit(failure("build-mcu", 2, "Missing --project-path"), as_json)
            parameters.extend(["-Project", project_path])
            for source, target in (
                ("--keil-target", "-Target"),
                ("--artifact-name", "-ArtifactName"),
                ("--output-directory", "-OutputDirectory"),
            ):
                value = option(arguments, source)
                if value:
                    parameters.extend([target, value])
        return run_adapter(f"build-{arguments[1]}.py", parameters, as_json)
    if command == "log":
        if len(arguments) < 2 or arguments[1] != "tail":
            return emit(failure("log", 2, "Only log tail is supported"), as_json)
        return run_adapter(
            "log-tail.py",
            ["-Kind", option(arguments, "--kind", "build") or "build", "-Since", option(arguments, "--since", "10m") or "10m"],
            as_json,
        )
    if command == "rtt":
        if len(arguments) < 2 or arguments[1] != "capture":
            return emit(failure("rtt", 2, "Only rtt capture is supported"), as_json)
        workspace = option(arguments, "--workspace")
        if not workspace:
            return emit(failure("rtt-capture-mcu", 2, "Missing --workspace"), as_json)
        parameters = ["-Workspace", workspace, "-WaitMs", option(arguments, "--wait-ms", "12000") or "12000"]
        if flag(arguments, "--reset"):
            if not flag(arguments, "--require-confirm"):
                return emit(
                    failure(
                        "rtt-capture-mcu",
                        2,
                        "RTT reset capture requires --require-confirm",
                        blocked=True,
                        requires_human_confirm=True,
                        gate={"level": "L3", "mode": "reset", "requires_human_confirm": True, "confirmed": False},
                    ),
                    as_json,
                )
            if not flag(arguments, "--confirm"):
                return emit(
                    failure(
                        "rtt-capture-mcu",
                        3,
                        "RTT reset capture gate is closed until a human passes --confirm",
                        blocked=True,
                        requires_human_confirm=True,
                        gate={"level": "L3", "mode": "reset", "requires_human_confirm": True, "confirmed": False},
                    ),
                    as_json,
                )
            parameters.append("-Reset")
        return run_adapter("rtt-capture-mcu.py", parameters, as_json)
    if command == "artifact":
        if len(arguments) < 2 or arguments[1] != "latest":
            return emit(failure("artifact", 2, "Only artifact latest is supported"), as_json)
        workspace_value = option(arguments, "--workspace")
        if not workspace_value:
            return emit(failure("artifact-latest", 2, "Missing --workspace"), as_json)
        workspace = Path(workspace_value)
        artifact = latest_artifact(workspace) if workspace.is_dir() else None
        return emit(
            result(bool(artifact), "artifact-latest", 0 if artifact else 1, workspace=str(workspace), artifact=artifact, first_failure=None if artifact else "No artifact found"),
            as_json,
        )
    if command == "flash":
        if len(arguments) < 2:
            return emit(failure("flash", 2, "Missing flash target"), as_json)
        target = arguments[1]
        if not flag(arguments, "--require-confirm"):
            return emit(failure(f"flash-{target}", 2, "Flash requires --require-confirm", requires_human_confirm=True), as_json)
        if not flag(arguments, "--confirm"):
            return emit(failure(f"flash-{target}", 3, "Flash gate is closed until a human passes --confirm", requires_human_confirm=True), as_json)
        if target != "mcu":
            return emit(failure(f"flash-{target}", 4, "MPU flash is handled directly by the Python Runtime"), as_json)
        workspace = option(arguments, "--workspace")
        if not workspace:
            return emit(failure("flash-mcu", 2, "Missing --workspace"), as_json)
        project_path = option(arguments, "--project-path")
        if not project_path:
            return emit(failure("flash-mcu", 2, "Missing --project-path"), as_json)
        parameters = ["-Workspace", workspace, "-Project", project_path]
        keil_target = option(arguments, "--keil-target")
        if keil_target:
            parameters.extend(["-Target", keil_target])
        artifact_name = option(arguments, "--artifact-name")
        if artifact_name:
            parameters.extend(["-ArtifactName", artifact_name])
        output_directory = option(arguments, "--output-directory")
        if output_directory:
            parameters.extend(["-OutputDirectory", output_directory])
        return run_adapter("flash-mcu.py", parameters, as_json)
    return emit(failure("agentctl", 2, f"Unknown subcommand: {command}"), as_json)


if __name__ == "__main__":
    raise SystemExit(main())
