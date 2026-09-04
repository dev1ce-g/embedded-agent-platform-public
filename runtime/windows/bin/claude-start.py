#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from agent_backend_common import *


def task_data(directory: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((directory / "task.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def resolve_task(workspace: Path, requested: str | None) -> dict[str, Any]:
    root = workspace / ".trellis" / "tasks"
    if not root.is_dir():
        return {"task_dir": None, "task_ref": None, "source": "none", "reason": "No .trellis/tasks directory found"}
    if requested:
        candidate = Path(requested)
        if not candidate.is_absolute():
            parts = candidate.parts
            candidate = workspace / candidate if parts[:2] == (".trellis", "tasks") else root / candidate
        if candidate.is_dir():
            return {"task_dir": candidate, "task_ref": f".trellis/tasks/{candidate.name}", "source": "explicit", "reason": "Resolved from --task"}
        for directory in root.iterdir():
            data = task_data(directory) if directory.is_dir() else None
            if data and requested in {data.get("id"), data.get("name")}:
                return {"task_dir": directory, "task_ref": f".trellis/tasks/{directory.name}", "source": "explicit", "reason": "Resolved --task from task.json id/name"}
        raise ValueError(f"Task not found in workspace: {requested}")
    candidates = []
    for directory in root.iterdir():
        data = task_data(directory) if directory.is_dir() else None
        if data and data.get("status") == "in_progress" and (directory / "job-packet.md").is_file():
            candidates.append(directory)
    if len(candidates) == 1:
        directory = candidates[0]
        return {"task_dir": directory, "task_ref": f".trellis/tasks/{directory.name}", "source": "auto-single-in-progress-job-packet", "reason": "Exactly one in_progress task with job-packet.md"}
    reason = "No in_progress task with job-packet.md found" if not candidates else "Multiple in_progress tasks with job-packet.md found: " + ", ".join(item.name for item in candidates)
    return {"task_dir": None, "task_ref": None, "source": "none", "reason": reason}


def initialize_session(workspace: Path, resolved: dict[str, Any], context_id: str | None) -> dict[str, Any] | None:
    directory = resolved["task_dir"]
    if directory is None:
        return None
    context = re.sub(r"[^A-Za-z0-9_.-]", "_", context_id or f"remote-claude-{directory.name}") or "unknown-task"
    session_dir = workspace / ".trellis" / ".runtime" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / f"{context}.json"
    session_path.write_text(json.dumps({"platform": "claude", "session_id": context, "current_task": resolved["task_ref"], "current_run": None, "workspace": str(workspace.resolve()), "source": "hq claude", "task_source": resolved["source"], "last_seen_at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"context_id": context, "session_file": str(session_path), "current_task": resolved["task_ref"], "task_source": resolved["source"], "task_reason": resolved["reason"]}


def prompt_text(args: argparse.Namespace, workspace: Path, resolved: dict[str, Any]) -> str:
    if args.PromptBase64:
        return base64.b64decode(args.PromptBase64, validate=True).decode("utf-8")
    if args.PromptFile:
        return Path(args.PromptFile).read_text(encoding="utf-8-sig")
    if args.Prompt:
        return args.Prompt
    directory = resolved["task_dir"]
    if directory is None:
        raise ValueError("Cannot execute Claude without --prompt, --prompt-file, or a resolved Trellis task")
    packet = directory / "job-packet.md"
    if not packet.is_file():
        raise ValueError(f"Resolved task has no job-packet.md: {directory}")
    read = lambda name: (directory / name).read_text(encoding="utf-8-sig") if (directory / name).is_file() else ""
    return f"""You are the Windows Embedded Project Agent for a Trellis task.

Active task: {resolved['task_ref']}
Workspace: {workspace}

Project rules:
- Treat job-packet.md as the authority for ownership, objective, write paths, forbidden actions, evidence and handoff.
- Own requirements, architecture, implementation and verification when the task contract assigns the complete project; do not assume an execution-only role.
- Work only inside the authorized workspace and allowed write paths.
- Use the fixed embedded-agent Runtime Interface for Windows toolchains, Jenkins, J-Link, CAN, ADB, SDK and device operations.
- Flashing, security changes, destructive deletes, commits, pushes or branch rewrites require explicit permission and Gate confirmation.
- Return command names, exit codes, evidence paths and the first blocking failure.

=== job-packet.md ===
{read('job-packet.md')}

=== prd.md ===
{read('prd.md')}

=== context.generated.yaml ===
{read('context.generated.yaml')}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Workspace")
    parser.add_argument("-Task")
    parser.add_argument("-ContextId")
    parser.add_argument("-Execute", action="store_true")
    parser.add_argument("-Prompt")
    parser.add_argument("-PromptBase64")
    parser.add_argument("-PromptFile")
    parser.add_argument("-PermissionMode", default="auto")
    parser.add_argument("-OutputFormat", default="json")
    parser.add_argument("-Tools")
    parser.add_argument("-Model")
    parser.add_argument("-MaxBudgetUsd")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    if not args.Workspace:
        return emit(failure("claude", 2, "Missing -Workspace"), args.Json)
    workspace = Path(args.Workspace)
    if not workspace.is_dir():
        return emit(failure("claude", 2, f"Workspace not found: {workspace}"), args.Json)
    claude = shutil.which("claude")
    if not claude:
        return emit(failure("claude", 127, "claude command not found on remote host", workspace=str(workspace)), args.Json)
    try:
        resolved = resolve_task(workspace, args.Task)
        session = initialize_session(workspace, resolved, args.ContextId)
    except (OSError, ValueError) as exc:
        return emit(failure("claude", 2, str(exc), workspace=str(workspace)), args.Json)
    if args.Execute:
        if session is None:
            return emit(failure("claude-execute", 1, f"Cannot execute Claude agent without Trellis runtime session: {resolved['reason']}", workspace=str(workspace)), args.Json)
        try:
            prompt = prompt_text(args, workspace, resolved)
        except (OSError, ValueError) as exc:
            return emit(failure("claude-execute", 1, str(exc), workspace=str(workspace), active_task=resolved["task_ref"]), args.Json)
        safe_task = re.sub(r"[^A-Za-z0-9_.-]", "_", session["current_task"]) or "unknown-task"
        prompt_log = new_log_path(f"claude-agent-{safe_task}", ".prompt.txt")
        output_log = prompt_log.with_name(prompt_log.name.replace(".prompt.txt", ".out.log"))
        prompt_log.write_text(prompt, encoding="utf-8")
        command = [claude, "--bare", "-p", "--input-format", "text", "--output-format", args.OutputFormat, "--permission-mode", args.PermissionMode, "--name", f"trellis-{safe_task}"]
        if args.Model:
            command.extend(["--model", args.Model])
        if args.Tools is not None:
            command.extend(["--tools", "" if args.Tools in {"none", "off", "disabled"} else args.Tools])
        if args.MaxBudgetUsd:
            command.extend(["--max-budget-usd", args.MaxBudgetUsd])
        environment = os.environ.copy()
        environment.update(TRELLIS_CONTEXT_ID=session["context_id"], CLAUDE_NON_INTERACTIVE="1")
        completed = subprocess.run(command, input=prompt.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=workspace, env=environment, check=False)
        output = (completed.stdout or b"").decode("utf-8", errors="replace").rstrip()
        output_log.write_text(output, encoding="utf-8")
        parsed = None
        if args.OutputFormat == "json" and output:
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                pass
        return emit(result(completed.returncode == 0, "claude-execute", completed.returncode, workspace=str(workspace.resolve()), executable=claude, active_task=resolved["task_ref"], active_task_source=resolved["source"], trellis_context_id=session["context_id"], trellis_runtime_session=session["session_file"], permission_mode=args.PermissionMode, output_format=args.OutputFormat, tools=args.Tools, prompt_log=str(prompt_log), output_log=str(output_log), output_preview=output[:4000], claude_output=parsed, timestamp=now_iso()), args.Json)
    if args.Json:
        claude_md = workspace / "CLAUDE.md"
        bootstrap = claude_md.is_file() and "TRELLIS_REMOTE_CLAUDE:START" in claude_md.read_text(encoding="utf-8-sig", errors="replace")
        return emit(result(True, "claude", workspace=str(workspace.resolve()), executable=claude, claude_md=str(claude_md.resolve()) if claude_md.is_file() else None, trellis_bootstrap=bootstrap, active_task=resolved["task_ref"], active_task_source=resolved["source"], active_task_reason=resolved["reason"], trellis_context_id=session["context_id"] if session else None, trellis_runtime_session=session["session_file"] if session else None, timestamp=now_iso()), True)
    environment = os.environ.copy()
    if session:
        environment["TRELLIS_CONTEXT_ID"] = session["context_id"]
    return subprocess.run([claude], cwd=workspace, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
