#!/usr/bin/env python3
"""Initialize an embedded project through official Trellis and stable runtimes."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "trellis-embedded-bootstrap/v1"
DEFAULT_TEMPLATE = "embedded-dual-machine-v1"
MIN_TRELLIS_VERSION = (0, 6, 5)
MAX_CAPTURE_CHARS = 8000
LOCAL_PROJECTION_PATHS = (".trellis/", ".agents/", ".codex/", ".claude/", "AGENTS.md")
WORKSPACE_MANIFEST_PATH = ".trellis/spec/project/workspace-manifest.json"
PROJECT_AGENTS_TEMPLATE_PATH = "marketplace/project-agents.md"
PROJECT_AGENTS_START = "<!-- EMBEDDED-AGENT-PLATFORM:START -->"
PROJECT_AGENTS_END = "<!-- EMBEDDED-AGENT-PLATFORM:END -->"
LEGACY_PROJECT_AGENTS_START = (
    "## Embedded Agent Platform\n\n"
    "The reusable embedded runtime is machine-level."
)
LEGACY_PROJECT_AGENTS_END = (
    "Preserve project-specific Knowledge and\n"
    "existing user changes during Trellis or Spec updates."
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="New or existing project directory")
    parser.add_argument("--trellis-command", default="trellis")
    parser.add_argument("--user", default=os.environ.get("USER", "developer"))
    parser.add_argument(
        "--registry",
        default=os.environ.get("TRELLIS_EMBEDDED_REGISTRY"),
    )
    parser.add_argument(
        "--template",
        default=os.environ.get("TRELLIS_EMBEDDED_TEMPLATE", DEFAULT_TEMPLATE),
    )
    parser.add_argument("--workflow", default="native")
    parser.add_argument("--workflow-source")
    parser.add_argument(
        "--local-template",
        action="store_true",
        help="Use the bundled spec-only template instead of the Git registry.",
    )
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--no-codex", action="store_true")
    parser.add_argument("--overwrite-spec", action="store_true")
    parser.add_argument("--skip-trellis-init", action="store_true")
    parser.add_argument(
        "--discovery",
        choices=("auto", "windows", "local", "skip"),
        default="auto",
    )
    parser.add_argument("--project-id")
    parser.add_argument("--windows-workspace")
    parser.add_argument("--windows-human-workspace")
    parser.add_argument("--windows-agent-workspace")
    parser.add_argument("--sync-mode", choices=("git",), default="git")
    parser.add_argument("--embedded-agent-command")
    parser.add_argument("--keil-project", "--mcu-keil-project", dest="mcu_keil_project")
    parser.add_argument("--build-knowledge", action="store_true")
    parser.add_argument(
        "--no-git-exclude",
        action="store_true",
        help="Do not add local Trellis projection paths to .git/info/exclude.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--preset", default="embedded-dual-machine", help=argparse.SUPPRESS)
    parser.add_argument("--no-copy-skills", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.local_template:
        args.registry = None
    if args.windows_agent_workspace and not args.project_id:
        parser.error("--windows-agent-workspace requires --project-id")
    if args.windows_human_workspace and not args.project_id:
        parser.error("--windows-human-workspace requires --project-id")
    if args.windows_workspace and args.windows_agent_workspace:
        parser.error("use --windows-workspace or --windows-agent-workspace, not both")
    if args.windows_agent_workspace:
        args.windows_workspace = args.windows_agent_workspace
    return args


def command_prefix(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("command must not be empty")
    return parts


def build_init_command(args: argparse.Namespace) -> list[str]:
    command = [
        *command_prefix(args.trellis_command),
        "init",
        "--yes",
        "--user",
        args.user,
        "--workflow",
        args.workflow,
    ]
    if not args.no_codex:
        command.append("--codex")
    if args.claude:
        command.append("--claude")
    if args.registry:
        command.extend(["--registry", args.registry, "--template", args.template])
        command.append("--overwrite" if args.overwrite_spec else "--append")
    if args.workflow_source:
        command.extend(["--workflow-source", args.workflow_source])
    return command


def embedded_agent_prefix(args: argparse.Namespace) -> list[str]:
    if args.embedded_agent_command:
        return command_prefix(args.embedded_agent_command)
    installed = shutil.which("embedded-agent")
    if installed:
        return [installed]
    bundled_client = (
        Path(__file__).resolve().parents[1]
        / "runtime"
        / "mac"
        / "bin"
        / "embedded-agent"
    )
    return [str(bundled_client)]


def discovery_mode(args: argparse.Namespace) -> str:
    has_project = bool(args.project_id)
    has_workspace = bool(args.windows_workspace)
    if has_project != has_workspace:
        raise ValueError(
            "--project-id and --windows-workspace must be provided together"
        )
    if args.discovery == "auto":
        return "windows" if has_project else "local"
    if args.discovery == "windows" and not (has_project and has_workspace):
        raise ValueError(
            "Windows discovery requires --project-id and --windows-workspace"
        )
    return args.discovery


def git_command(target: Path, arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(target), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def discover_git_repositories(target: Path) -> list[dict[str, Any]]:
    candidates = [target]
    try:
        candidates.extend(path for path in sorted(target.iterdir()) if path.is_dir() and not path.name.startswith("."))
    except OSError:
        pass
    repositories: list[dict[str, Any]] = []
    for repo in candidates:
        if not (repo / ".git").exists():
            continue
        root = git_command(repo, ["rev-parse", "--show-toplevel"])
        commit = git_command(repo, ["rev-parse", "HEAD"])
        remote = git_command(repo, ["remote", "get-url", "origin"])
        branch = git_command(repo, ["symbolic-ref", "--short", "HEAD"])
        if not root or not commit:
            continue
        try:
            relative = Path(root).resolve().relative_to(target.resolve()).as_posix() or "."
        except ValueError:
            continue
        repositories.append({"path": relative, "remote": remote or None, "branch": branch or None, "commit": commit})
    return repositories


def write_workspace_manifest(target: Path, args: argparse.Namespace, dry_run: bool) -> dict[str, Any]:
    repositories = discover_git_repositories(target) if not dry_run else []
    manifest: dict[str, Any] = {
        "schema_version": "embedded-workspace-manifest/v1",
        "project_id": args.project_id,
        "sync_mode": args.sync_mode,
        "human_workspace": args.windows_human_workspace,
        "agent_workspace": args.windows_workspace,
        "source_workspace": str(target.resolve()),
        "repositories": repositories,
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    path = target / WORKSPACE_MANIFEST_PATH
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"name": "workspace-manifest", "ok": True, "exit_code": 0, "path": str(path), "manifest": manifest}


def truncate(value: str) -> str:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value
    return value[:MAX_CAPTURE_CHARS] + "\n...[truncated]"


def run_step(
    name: str,
    command: list[str],
    cwd: Path,
    dry_run: bool,
    quiet: bool,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "dry_run": dry_run,
    }
    if dry_run:
        step.update({"ok": True, "exit_code": 0})
        if not quiet:
            print(f"[dry-run] {shlex.join(command)}")
        return step

    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    step.update(
        {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": truncate(completed.stdout.strip()),
            "stderr": truncate(completed.stderr.strip()),
        }
    )
    if not quiet:
        print(f"[{name}] exit={completed.returncode}")
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
    return step


def extract_version(output: str) -> tuple[int, int, int] | None:
    matches = re.findall(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", output)
    if not matches:
        return None
    return tuple(int(part) for part in matches[-1])


def command_reported_error(step: dict[str, Any]) -> str | None:
    text = f"{step.get('stdout', '')}\n{step.get('stderr', '')}"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(("error:", "fatal:")):
            return stripped
    return None


def configure_local_git_exclude(target: Path, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": "local-git-exclude",
        "ok": True,
        "changed": False,
        "dry_run": dry_run,
    }
    completed = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel", "--git-path", "info/exclude"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or len(lines) < 2:
        result["skipped"] = "target is not inside a Git worktree"
        return result

    git_root = Path(lines[0]).resolve()
    exclude_path = Path(lines[1])
    if not exclude_path.is_absolute():
        exclude_path = (target / exclude_path).resolve()
    try:
        prefix = target.resolve().relative_to(git_root).as_posix()
    except ValueError:
        result["skipped"] = "target is outside the resolved Git worktree"
        return result

    entries = [f"{prefix}/{item}" if prefix != "." else item for item in LOCAL_PROJECTION_PATHS]
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    existing_lines = {line.strip() for line in existing.splitlines()}
    missing = [entry for entry in entries if entry not in existing_lines]
    result.update(
        {
            "git_root": str(git_root),
            "exclude_path": str(exclude_path),
            "entries": entries,
            "added": missing,
            "changed": bool(missing),
        }
    )
    if not missing or dry_run:
        return result

    block = "# Embedded Agent Platform local projection\n" + "\n".join(missing) + "\n"
    separator = "" if not existing or existing.endswith("\n") else "\n"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    exclude_path.write_text(existing + separator + block, encoding="utf-8")
    return result


def project_agents_template() -> str:
    path = Path(__file__).resolve().parents[1] / PROJECT_AGENTS_TEMPLATE_PATH
    return path.read_text(encoding="utf-8").strip() + "\n"


def merge_managed_block(existing: str, managed: str) -> tuple[str, str]:
    start_count = existing.count(PROJECT_AGENTS_START)
    end_count = existing.count(PROJECT_AGENTS_END)
    if start_count != end_count or start_count > 1:
        raise ValueError("AGENTS.md has malformed Embedded Agent Platform markers")
    if start_count == 1:
        start = existing.index(PROJECT_AGENTS_START)
        end_position = existing.find(PROJECT_AGENTS_END, start)
        if end_position < 0:
            raise ValueError("AGENTS.md has malformed Embedded Agent Platform markers")
        end = end_position + len(PROJECT_AGENTS_END)
        suffix = existing[end:]
        replacement = existing[:start] + managed.rstrip("\n") + suffix
        return replacement.rstrip() + "\n", "updated"
    if LEGACY_PROJECT_AGENTS_START in existing:
        start = existing.index(LEGACY_PROJECT_AGENTS_START)
        legacy_end = existing.find(LEGACY_PROJECT_AGENTS_END, start)
        if legacy_end < 0:
            raise ValueError("AGENTS.md has an incomplete legacy Embedded Agent Platform block")
        end = legacy_end + len(LEGACY_PROJECT_AGENTS_END)
        replacement = existing[:start] + managed.rstrip("\n") + existing[end:]
        return replacement.rstrip() + "\n", "updated"
    if not existing.strip():
        return managed, "created"
    return existing.rstrip() + "\n\n" + managed, "updated"


def install_project_agents(target: Path, dry_run: bool) -> dict[str, Any]:
    destination = target / "AGENTS.md"
    managed = project_agents_template()
    existing = destination.read_text(encoding="utf-8") if destination.exists() else ""
    try:
        merged, action = merge_managed_block(existing, managed)
    except ValueError as error:
        return {
            "name": "project-agents",
            "ok": False,
            "path": str(destination),
            "error": str(error),
        }
    if merged == existing:
        action = "skipped"
    if not dry_run and merged != existing:
        destination.write_text(merged, encoding="utf-8")
    return {
        "name": "project-agents",
        "ok": True,
        "path": str(destination),
        "action": action,
        "changed": merged != existing,
        "dry_run": dry_run,
    }


def local_fallback_command(args: argparse.Namespace, target: Path) -> list[str]:
    script = Path(__file__).resolve().with_name("embedded_spec_installer.py")
    command = [
        sys.executable,
        str(script),
        "--target",
        str(target),
        "--json",
    ]
    if args.overwrite_spec:
        command.append("--overwrite")
    return command


def local_discovery_command(target: Path) -> list[str]:
    script = Path(__file__).resolve().with_name("project_discovery.py")
    return [
        sys.executable,
        str(script),
        "--root",
        str(target),
        "--json-summary",
    ]


def windows_commands(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    prefix = embedded_agent_prefix(args)
    discovery_command = [
        *prefix,
        "project",
        "discover",
        "--project",
        args.project_id,
        "--workspace",
        args.windows_workspace,
        "--write-background",
        "--json",
    ]
    if args.mcu_keil_project:
        discovery_command.extend(["--keil-project", args.mcu_keil_project])
    commands = [
        ("windows-agent-status", [*prefix, "status", "--json"]),
        ("windows-project-discovery", discovery_command),
    ]
    if args.build_knowledge:
        commands.append(
            (
                "windows-knowledge-build",
                [
                    *prefix,
                    "knowledge",
                    "build",
                    "--project",
                    args.project_id,
                    "--write",
                    "--json",
                ],
            )
        )
    return commands


def fail_report(report: dict[str, Any], message: str, code: int = 2) -> int:
    report.update({"ok": False, "error": message})
    print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    target = args.target.resolve()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "target": str(target),
        "spec_mode": "registry" if args.registry else "bundled-fallback",
        "workflow": args.workflow,
        "steps": [],
    }

    if args.preset != "embedded-dual-machine":
        return fail_report(report, f"unsupported compatibility preset: {args.preset}")

    try:
        mode = discovery_mode(args)
    except ValueError as error:
        return fail_report(report, str(error))
    report["discovery_mode"] = mode

    if args.skip_trellis_init and args.registry:
        return fail_report(
            report,
            "--skip-trellis-init cannot install a registry template; rerun without it",
        )
    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    version_step = run_step(
        "trellis-version",
        [*command_prefix(args.trellis_command), "--version"],
        target if target.exists() else Path.cwd(),
        args.dry_run,
        args.json,
    )
    report["steps"].append(version_step)
    if not version_step["ok"]:
        return fail_report(report, "Trellis CLI is not available", version_step["exit_code"])
    if not args.dry_run:
        version = extract_version(
            f"{version_step.get('stdout', '')}\n{version_step.get('stderr', '')}"
        )
        if version is None or version < MIN_TRELLIS_VERSION:
            return fail_report(
                report,
                "Trellis 0.6.5 or newer is required for registry/workflow init flags",
            )
        report["trellis_version"] = ".".join(str(part) for part in version)

    if not args.skip_trellis_init:
        init_step = run_step(
            "trellis-init",
            build_init_command(args),
            target,
            args.dry_run,
            args.json,
        )
        report["steps"].append(init_step)
        if not init_step["ok"]:
            return fail_report(report, "official trellis init failed", init_step["exit_code"])
        semantic_error = command_reported_error(init_step)
        if semantic_error:
            return fail_report(report, semantic_error)

        expected_spec = target / ".trellis" / "spec" / "index.md"
        if args.registry and not args.dry_run and not expected_spec.is_file():
            return fail_report(
                report,
                "Trellis returned success but the selected Spec template was not installed",
            )

    if not args.registry:
        fallback_step = run_step(
            "embedded-spec-fallback",
            local_fallback_command(args, target),
            target,
            args.dry_run,
            args.json,
        )
        report["steps"].append(fallback_step)
        if not fallback_step["ok"]:
            return fail_report(report, "bundled embedded Spec install failed", fallback_step["exit_code"])

    agents_step = install_project_agents(target, args.dry_run)
    report["steps"].append(agents_step)
    if not agents_step["ok"]:
        return fail_report(report, agents_step["error"])

    if not args.no_git_exclude:
        exclude_step = configure_local_git_exclude(target, args.dry_run)
        report["steps"].append(exclude_step)

    if mode == "windows":
        manifest_step = write_workspace_manifest(target, args, args.dry_run)
        report["steps"].append(manifest_step)
        report["workspace_manifest"] = manifest_step["manifest"]

    if mode == "local":
        discovery_step = run_step(
            "local-project-discovery",
            local_discovery_command(target),
            target,
            args.dry_run,
            args.json,
        )
        report["steps"].append(discovery_step)
        if not discovery_step["ok"]:
            return fail_report(report, "local project discovery failed", discovery_step["exit_code"])
    elif mode == "windows":
        for name, command in windows_commands(args):
            step = run_step(name, command, target, args.dry_run, args.json)
            report["steps"].append(step)
            if not step["ok"]:
                return fail_report(report, f"{name} failed", step["exit_code"])

    report["ok"] = True
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"embedded bootstrap complete: spec={report['spec_mode']} "
            f"workflow={args.workflow} discovery={mode}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
