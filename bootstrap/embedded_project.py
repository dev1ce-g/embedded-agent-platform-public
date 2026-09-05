#!/usr/bin/env python3
"""Initialize and maintain a model-independent embedded project projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from .rule_bundle_installer import (
        BUNDLE_ID,
        LOCK_SCHEMA_VERSION,
        RULE_DESTINATION,
        RULE_SOURCE,
        install_rules,
        source_root,
    )
except ImportError:  # Direct script/shim execution.
    from rule_bundle_installer import (
        BUNDLE_ID,
        LOCK_SCHEMA_VERSION,
        RULE_DESTINATION,
        RULE_SOURCE,
        install_rules,
        source_root,
    )


SCHEMA_VERSION = "embedded-project-command/v1"
MANIFEST_SCHEMA_VERSION = "embedded-agent-project/v1"
WORKSPACE_SCHEMA_VERSION = "embedded-workspace-manifest/v2"
KNOWLEDGE_SCHEMA_VERSION = "embedded-knowledge-index/v1"
MIGRATION_SCHEMA_VERSION = "embedded-trellis-migration/v1"
PLATFORM_VERSION_FILE = Path("VERSION")
MAX_CAPTURE_CHARS = 8000
CAPABILITY_RESULT_SCHEMA_VERSION = "embedded-capability-result/v1"
PROJECTION_ROOT = Path(".embedded-agent")
MANIFEST_PATH = PROJECTION_ROOT / "manifest.json"
CONTEXT_PATH = PROJECTION_ROOT / "context"
KNOWLEDGE_PATH = PROJECTION_ROOT / "knowledge"
WORKSPACE_MANIFEST_PATH = CONTEXT_PATH / "workspace-manifest.json"
KNOWLEDGE_INDEX_PATH = CONTEXT_PATH / "knowledge-index.json"
MIGRATION_REPORT_PATH = CONTEXT_PATH / "trellis-migration.json"
PROJECT_AGENTS_TEMPLATE_PATH = Path("rules/project-agents.md")
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
LOCAL_PROJECTION_PATHS = (
    ".embedded-agent/manifest.json",
    ".embedded-agent/rules/platform/",
    ".embedded-agent/context/",
    ".embedded-agent/evidence/",
)
DEFAULT_KNOWLEDGE_SOURCES = (
    "README.md",
    "README.zh-CN.md",
    "CONTRIBUTING.md",
    "docs",
    ".embedded-agent/rules/project",
    ".embedded-agent/knowledge",
)
KNOWLEDGE_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
LEGACY_PLATFORM_RULE_PATHS = {
    "agent-governance.md",
    "architecture-boundaries.md",
    "coding-rules.md",
    "config-and-generated-files.md",
    "embedded-runtime-workflow.md",
    "evidence-first-engineering.md",
    "git-conventions.md",
    "index.md",
    "jenkins-workflow.md",
    "mcu/project/index.md",
    "native-subagent-workflow.md",
    "platform-operating-model.md",
    "project-context.md",
    "project-discovery.md",
    "project-onboarding.md",
    "repository-layout.md",
    "requirement-intake-template.md",
    "requirement-intake.md",
    "safety-and-security.md",
    "soc-integration-boundaries.md",
    "third-party-and-sdk-boundary.md",
    "verification.md",
}
class ProjectError(ValueError):
    """A safe, user-actionable project projection failure."""


def platform_version() -> str:
    """Read the platform release version from the repository root."""
    try:
        value = (source_root() / PLATFORM_VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return value or "unknown"


PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_project_id(value: str) -> str:
    candidate = value.strip()
    stem = candidate.split(".", 1)[0].upper()
    if (
        not PROJECT_ID_PATTERN.fullmatch(candidate)
        or candidate in {".", ".."}
        or candidate.endswith(".")
        or stem in WINDOWS_RESERVED_NAMES
    ):
        raise ProjectError(
            "project id must be 1-128 ASCII letters, digits, dots, underscores, or "
            "hyphens; it must start with a letter or digit and not be a reserved name"
        )
    return candidate


def derived_project_id(value: str) -> str:
    candidate = value.strip()
    try:
        return safe_project_id(candidate)
    except ProjectError:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", candidate).strip("._-") or "project"
        if not slug[0].isalnum() or slug.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            slug = f"project-{slug}"
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
        return f"{slug[:116]}-{digest}"


def hash_file(path: Path) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    size = 0
    preview = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if len(preview) < 65536:
                preview += chunk[: 65536 - len(preview)]
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size, preview


def validate_output_path(root: Path, path: Path) -> None:
    """Reject output paths that escape root or traverse a symlink."""
    safe_root = root.resolve()
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(safe_root)
    except ValueError as error:
        raise ProjectError(f"write destination escapes project root: {path}") from error
    current = safe_root
    for index, part in enumerate(relative.parts):
        current = current / part
        if current.is_symlink():
            raise ProjectError(f"refusing to write through symlink: {current}")
        if current.exists():
            is_final = index == len(relative.parts) - 1
            if is_final and not current.is_file():
                raise ProjectError(f"write destination is not a regular file: {current}")
            if not is_final and not current.is_dir():
                raise ProjectError(f"write parent is not a directory: {current}")


def atomic_write_bytes(
    path: Path,
    content: bytes,
    dry_run: bool = False,
    *,
    root: Path | None = None,
) -> bool:
    if root is not None:
        validate_output_path(root, path)
    if path.is_symlink():
        raise ProjectError(f"refusing to write through symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise ProjectError(f"write destination is not a regular file: {path}")
        if path.read_bytes() == content:
            return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    if root is not None:
        validate_output_path(root, path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return True


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def truncate(value: str) -> str:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value
    return value[:MAX_CAPTURE_CHARS] + "\n...[truncated]"


def valid_contract_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


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
        step.update({"ok": True, "exit_code": 0, "skipped": "dry-run"})
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
    stdout = completed.stdout.strip()
    protocol_failure: str | None = None
    if completed.returncode == 0 and "--json" in command:
        expected_operations = {
            "windows-agent-status": "status",
            "windows-project-discovery": "project-discover",
            "windows-knowledge-build": "knowledge-build",
        }
        if not stdout:
            protocol_failure = "JSON command returned empty stdout"
        else:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                protocol_failure = "JSON command returned a non-JSON stdout payload"
            else:
                required = {
                    "schema_version",
                    "contract_version",
                    "capability_id",
                    "phase",
                    "state",
                    "operation",
                    "ok",
                    "exit_code",
                    "timestamp",
                    "evidence",
                    "error",
                }
                if not isinstance(payload, dict):
                    protocol_failure = "JSON command did not return an object"
                elif required - set(payload):
                    protocol_failure = "JSON command returned an incomplete Capability Contract envelope"
                elif payload.get("schema_version") != CAPABILITY_RESULT_SCHEMA_VERSION:
                    protocol_failure = "JSON command returned an unsupported result schema"
                elif not str(payload.get("contract_version", "")).startswith("1."):
                    protocol_failure = "JSON command returned an unsupported Capability Contract version"
                elif not isinstance(payload.get("capability_id"), str) or not payload["capability_id"]:
                    protocol_failure = "JSON command returned an invalid capability_id"
                elif payload.get("phase") not in {"discover", "preflight", "execute", "status", "evidence"}:
                    protocol_failure = "JSON command returned an invalid phase"
                elif payload.get("state") != "succeeded":
                    protocol_failure = "JSON command did not reach a succeeded state"
                elif payload.get("operation") != expected_operations.get(name):
                    protocol_failure = "JSON command returned an unexpected operation"
                elif type(payload.get("exit_code")) is not int or payload.get("exit_code") != completed.returncode:
                    protocol_failure = "JSON command exit_code does not match the process exit code"
                elif not valid_contract_timestamp(payload.get("timestamp")):
                    protocol_failure = "JSON command returned an invalid timestamp"
                elif not isinstance(payload.get("evidence"), list):
                    protocol_failure = "JSON command returned invalid evidence"
                elif payload.get("error") is not None:
                    protocol_failure = "Successful JSON command returned an error"
                elif payload.get("ok") is not True:
                    error = payload.get("error")
                    error_message = error.get("message") if isinstance(error, dict) else error
                    protocol_failure = str(
                        payload.get("first_failure")
                        or error_message
                        or "command reported failure"
                    )
    step.update(
        {
            "ok": completed.returncode == 0 and protocol_failure is None,
            "exit_code": completed.returncode,
            "stdout": truncate(stdout),
            "stderr": truncate(completed.stderr.strip()),
        }
    )
    if protocol_failure:
        step["first_failure"] = protocol_failure
    if not quiet:
        print(f"[{name}] exit={completed.returncode}")
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
    return step


def read_json(path: Path, schema: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid JSON file: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProjectError(f"JSON object required: {path}")
    if schema and value.get("schema_version") != schema:
        raise ProjectError(f"unsupported schema in {path}: {value.get('schema_version')}")
    return value


def validate_project_manifest(value: dict[str, Any], path: Path) -> dict[str, Any]:
    project_id = value.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ProjectError(f"project_id is missing from {path}")
    safe_project_id(project_id)
    if not isinstance(value.get("workspace"), dict):
        raise ProjectError(f"workspace object is missing from {path}")
    sources = value.get("knowledge_sources")
    if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
        raise ProjectError(f"knowledge_sources must be a string array in {path}")
    discovery = value.get("discovery")
    if not isinstance(discovery, dict) or discovery.get("default_adapter") not in {"local", "windows"}:
        raise ProjectError(f"discovery.default_adapter is invalid in {path}")
    return value


def read_project_manifest(path: Path) -> dict[str, Any]:
    return validate_project_manifest(read_json(path, MANIFEST_SCHEMA_VERSION), path)


def project_agents_template() -> str:
    path = source_root() / PROJECT_AGENTS_TEMPLATE_PATH
    try:
        managed = path.read_text(encoding="utf-8").strip() + "\n"
    except OSError as error:
        raise ProjectError(f"project AGENTS template not found: {path}") from error
    block_start = managed.find(PROJECT_AGENTS_START)
    block_end = managed.find(PROJECT_AGENTS_END, block_start + len(PROJECT_AGENTS_START))
    if block_start < 0 or block_end < 0:
        raise ProjectError(f"project AGENTS template has invalid platform markers: {path}")
    active_block = managed[block_start:block_end]
    if ".trellis" in active_block.lower() or "trellis" in active_block.lower():
        raise ProjectError(f"project AGENTS template still depends on Trellis: {path}")
    return managed


def merge_managed_block(existing: str, managed: str) -> tuple[str, str]:
    start_count = existing.count(PROJECT_AGENTS_START)
    end_count = existing.count(PROJECT_AGENTS_END)
    if start_count != end_count or start_count > 1:
        raise ProjectError("AGENTS.md has malformed Embedded Agent Platform markers")
    if start_count == 1:
        start = existing.index(PROJECT_AGENTS_START)
        end_position = existing.find(PROJECT_AGENTS_END, start)
        if end_position < start:
            raise ProjectError("AGENTS.md has malformed Embedded Agent Platform markers")
        end = end_position + len(PROJECT_AGENTS_END)
        newline = "\r\n" if "\r\n" in existing else "\n"
        block = managed.rstrip("\n").replace("\n", newline)
        return existing[:start] + block + existing[end:], "updated"
    if LEGACY_PROJECT_AGENTS_START in existing:
        start = existing.index(LEGACY_PROJECT_AGENTS_START)
        legacy_end = existing.find(LEGACY_PROJECT_AGENTS_END, start)
        if legacy_end < 0:
            raise ProjectError("AGENTS.md has an incomplete legacy Embedded Agent Platform block")
        end = legacy_end + len(LEGACY_PROJECT_AGENTS_END)
        newline = "\r\n" if "\r\n" in existing else "\n"
        block = managed.rstrip("\n").replace("\n", newline)
        return existing[:start] + block + existing[end:], "updated"
    if not existing:
        return managed, "created"
    newline = "\r\n" if "\r\n" in existing else "\n"
    separator = "" if existing.endswith(("\n", "\r")) else newline
    return existing + separator + newline + managed.replace("\n", newline), "updated"


def plan_project_agents(target: Path) -> tuple[Path, bytes, dict[str, Any]]:
    destination = target / "AGENTS.md"
    existing_bytes = destination.read_bytes() if destination.exists() else b""
    if destination.exists() and (not destination.is_file() or destination.is_symlink()):
        raise ProjectError(f"AGENTS.md is not a regular file: {destination}")
    try:
        existing = existing_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError(f"AGENTS.md is not UTF-8: {destination}") from error
    merged, action = merge_managed_block(existing, project_agents_template())
    encoded = merged.encode("utf-8")
    if encoded == existing_bytes:
        action = "skipped"
    return destination, encoded, {
        "name": "project-agents",
        "ok": True,
        "path": str(destination),
        "action": action,
        "changed": encoded != existing_bytes,
    }


def install_project_agents(target: Path, dry_run: bool) -> dict[str, Any]:
    destination, encoded, result = plan_project_agents(target)
    atomic_write_bytes(destination, encoded, dry_run, root=target)
    result["dry_run"] = dry_run
    return result


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
        candidates.extend(
            path
            for path in sorted(target.iterdir())
            if path.is_dir() and not path.name.startswith(".")
        )
    except OSError:
        pass
    repositories: list[dict[str, Any]] = []
    for repo in candidates:
        root = git_command(repo, ["rev-parse", "--show-toplevel"])
        commit = git_command(repo, ["rev-parse", "HEAD"])
        if not root or not commit:
            continue
        try:
            relative = Path(root).resolve().relative_to(target.resolve()).as_posix() or "."
        except ValueError:
            continue
        if any(item["path"] == relative for item in repositories):
            continue
        repositories.append(
            {
                "path": relative,
                "remote": git_command(repo, ["remote", "get-url", "origin"]) or None,
                "branch": git_command(repo, ["symbolic-ref", "--short", "HEAD"]) or None,
                "commit": commit,
                "dirty": bool(git_command(repo, ["status", "--porcelain=v1"])),
            }
        )
    return sorted(repositories, key=lambda item: item["path"])


def write_workspace_manifest(
    target: Path,
    manifest: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "project_id": manifest["project_id"],
        "source_workspace": str(target.resolve()),
        "sync_mode": manifest["workspace"]["sync_mode"],
        "human_workspace": manifest["workspace"].get("windows_human_workspace"),
        "agent_workspace": manifest["workspace"].get("windows_agent_workspace"),
        "repositories": [] if dry_run else discover_git_repositories(target),
    }
    digest_input = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value["manifest_sha256"] = hashlib.sha256(digest_input).hexdigest()
    path = target / WORKSPACE_MANIFEST_PATH
    changed = atomic_write_bytes(path, json_bytes(value), dry_run, root=target)
    return {
        "name": "workspace-manifest",
        "ok": True,
        "path": str(path),
        "changed": changed,
        "dry_run": dry_run,
        "manifest": value,
    }


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
    existing = exclude_path.read_bytes() if exclude_path.exists() else b""
    try:
        decoded = existing.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError(f"Git exclude is not UTF-8: {exclude_path}") from error
    existing_lines = {line.strip() for line in decoded.splitlines()}
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
    if not missing:
        return result
    separator = "" if not existing or existing.endswith(b"\n") else "\n"
    block = (
        separator
        + "# Embedded Agent Platform local projection\n"
        + "\n".join(missing)
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(exclude_path, existing + block, dry_run)
    return result


def discovery_mode(args: argparse.Namespace) -> str:
    has_project = bool(args.project_id)
    has_workspace = bool(args.windows_agent_workspace)
    if args.windows_human_workspace and not has_project:
        raise ProjectError("--windows-human-workspace requires --project-id")
    if has_workspace != has_project and (has_workspace or args.discovery == "windows"):
        raise ProjectError("--project-id and --windows-agent-workspace must be provided together")
    if args.discovery == "auto":
        return "windows" if has_workspace else "local"
    if args.discovery == "windows" and not (has_project and has_workspace):
        raise ProjectError("Windows discovery requires --project-id and --windows-agent-workspace")
    return args.discovery


def build_manifest(target: Path, args: argparse.Namespace, mode: str) -> dict[str, Any]:
    path = target / MANIFEST_PATH
    existing = read_project_manifest(path) if path.is_file() else {}
    requested_id = (
        safe_project_id(args.project_id)
        if args.project_id
        else derived_project_id(target.name)
    )
    if existing and args.project_id and existing.get("project_id") != requested_id:
        raise ProjectError(
            f"project id is already {existing.get('project_id')}; init cannot change it"
        )
    project_id = existing.get("project_id", requested_id)
    existing_workspace = existing.get("workspace", {})
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "layout_version": 1,
        "project_id": project_id,
        "rule_bundle": {"id": BUNDLE_ID, "path": RULE_DESTINATION.as_posix()},
        "paths": {
            "rules": (PROJECTION_ROOT / "rules").as_posix(),
            "context": CONTEXT_PATH.as_posix(),
            "knowledge": KNOWLEDGE_PATH.as_posix(),
        },
        "discovery": {"default_adapter": mode if mode != "skip" else existing.get("discovery", {}).get("default_adapter", "local")},
        "knowledge_sources": list(existing.get("knowledge_sources", DEFAULT_KNOWLEDGE_SOURCES)),
        "workspace": {
            "sync_mode": args.sync_mode or existing_workspace.get("sync_mode", "git"),
            "windows_human_workspace": args.windows_human_workspace or existing_workspace.get("windows_human_workspace"),
            "windows_agent_workspace": args.windows_agent_workspace or existing_workspace.get("windows_agent_workspace"),
        },
    }
    return manifest


def knowledge_documents(target: Path, sources: Iterable[str]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    index_path = (target / KNOWLEDGE_INDEX_PATH).resolve()
    for source_name in sources:
        source = target / source_name
        if not source.exists():
            continue
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in candidates:
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in KNOWLEDGE_SUFFIXES:
                continue
            if path.resolve() == index_path:
                continue
            try:
                relative = path.resolve().relative_to(target.resolve()).as_posix()
            except ValueError:
                continue
            if relative.startswith(".embedded-agent/knowledge/legacy-trellis-spec/"):
                continue
            if relative in seen:
                continue
            seen.add(relative)
            digest, size, preview = hash_file(path)
            title = path.stem
            if path.suffix.lower() == ".md":
                text = preview.decode("utf-8", errors="replace")
                heading = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
                if heading:
                    title = heading
            documents.append(
                {
                    "path": relative,
                    "title": title,
                    "sha256": digest,
                    "size": size,
                }
            )
    return sorted(documents, key=lambda item: item["path"])


def write_knowledge_index(target: Path, manifest: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    value = {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "project_id": manifest["project_id"],
        "sources": manifest["knowledge_sources"],
        "documents": knowledge_documents(target, manifest["knowledge_sources"]),
    }
    knowledge_root = target / KNOWLEDGE_PATH
    if not dry_run:
        knowledge_root.mkdir(parents=True, exist_ok=True)
    path = target / KNOWLEDGE_INDEX_PATH
    changed = atomic_write_bytes(path, json_bytes(value), dry_run, root=target)
    return {
        "name": "knowledge-index",
        "ok": True,
        "path": str(path),
        "changed": changed,
        "document_count": len(value["documents"]),
        "dry_run": dry_run,
    }


def embedded_agent_prefix() -> list[str]:
    adapter = "mac"
    if sys.platform.startswith("linux"):
        try:
            if "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(
                encoding="utf-8", errors="replace"
            ).lower():
                adapter = "wsl"
        except OSError:
            pass
    bundled_client = source_root() / "runtime" / adapter / "bin" / "embedded-agent"
    if not bundled_client.is_file() or bundled_client.is_symlink():
        raise ProjectError(f"bundled Runtime Adapter is unavailable: {bundled_client}")
    return [str(bundled_client)]


def local_discovery_command(target: Path, dry_run: bool) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve().with_name("project_discovery.py")),
        "--root",
        str(target),
        "--json-summary",
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def windows_commands(args: argparse.Namespace, manifest: dict[str, Any]) -> list[tuple[str, list[str]]]:
    prefix = embedded_agent_prefix()
    workspace = manifest["workspace"].get("windows_agent_workspace")
    if not workspace:
        raise ProjectError("Windows Agent workspace is not configured")
    discovery_command = [
        *prefix,
        "project",
        "discover",
        "--project",
        manifest["project_id"],
        "--workspace",
        workspace,
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
                    manifest["project_id"],
                    "--write",
                    "--json",
                ],
            )
        )
    return commands


def base_report(operation: str, target: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "target": str(target),
        "steps": [],
        "warnings": [],
    }


def install_projection(
    target: Path,
    args: argparse.Namespace,
    mode: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    # Parse all project-owned files before making the first local write.
    _, _, _ = plan_project_agents(target)
    validate_output_path(target, target / MANIFEST_PATH)
    manifest = build_manifest(target, args, mode)
    _, _ = install_rules(
        source_root() / RULE_SOURCE,
        target,
        overwrite=args.overwrite_rules,
        dry_run=True,
    )

    result, lock = install_rules(
        source_root() / RULE_SOURCE,
        target,
        overwrite=args.overwrite_rules,
        dry_run=args.dry_run,
    )
    report["steps"].append(
        {
            "name": "rule-bundle",
            "ok": True,
            "bundle_id": BUNDLE_ID,
            "bundle_sha256": lock["bundle_sha256"],
            "created": result.created,
            "updated": result.updated,
            "skipped": result.skipped,
            "candidates": result.candidates,
            "orphans": result.orphans,
            "dry_run": args.dry_run,
        }
    )
    manifest_changed = atomic_write_bytes(
        target / MANIFEST_PATH,
        json_bytes(manifest),
        args.dry_run,
        root=target,
    )
    report["steps"].append(
        {
            "name": "project-manifest",
            "ok": True,
            "path": str(target / MANIFEST_PATH),
            "changed": manifest_changed,
            "dry_run": args.dry_run,
        }
    )
    report["steps"].append(install_project_agents(target, args.dry_run))
    if not args.no_git_exclude:
        report["steps"].append(configure_local_git_exclude(target, args.dry_run))
    report["manifest"] = manifest
    if result.candidates:
        report["warnings"].append("Platform rule conflicts require review")
    return manifest


def refresh_projection(
    target: Path,
    args: argparse.Namespace,
    mode: str,
    manifest: dict[str, Any],
    report: dict[str, Any],
) -> bool:
    report["steps"].append(write_workspace_manifest(target, manifest, args.dry_run))
    report["steps"].append(write_knowledge_index(target, manifest, args.dry_run))
    if mode == "local":
        step = run_step(
            "local-project-discovery",
            local_discovery_command(target, args.dry_run),
            target,
            args.dry_run,
            args.json,
        )
        report["steps"].append(step)
        return bool(step["ok"])
    if mode == "windows":
        for name, command in windows_commands(args, manifest):
            step = run_step(name, command, target, args.dry_run, args.json)
            report["steps"].append(step)
            if not step["ok"]:
                return False
    return True


def ensure_target(target: Path) -> None:
    if not target.is_dir():
        raise ProjectError(f"project directory not found: {target}")
    projection = target / PROJECTION_ROOT
    if projection.exists() and (not projection.is_dir() or projection.is_symlink()):
        raise ProjectError(f"project projection is not a regular directory: {projection}")
    for relative in (RULE_DESTINATION, CONTEXT_PATH, KNOWLEDGE_PATH):
        path = target / relative
        if path.exists() and (not path.is_dir() or path.is_symlink()):
            raise ProjectError(f"projection path is not a regular directory: {path}")


def command_init(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    target = args.target.resolve()
    report = base_report("project-init", target)
    try:
        ensure_target(target)
        manifest_path = target / MANIFEST_PATH
        if args.discovery == "auto" and manifest_path.is_file() and not args.windows_agent_workspace:
            existing = read_project_manifest(manifest_path)
            mode = existing.get("discovery", {}).get("default_adapter", "local")
        else:
            mode = discovery_mode(args)
        report["discovery_mode"] = mode
        manifest = install_projection(target, args, mode, report)
        if mode != "skip" and not refresh_projection(target, args, mode, manifest, report):
            report.update({"ok": False, "error": f"{mode} project discovery failed"})
            return 1, report
        if mode == "skip":
            report["steps"].append(write_knowledge_index(target, manifest, args.dry_run))
        report["ok"] = True
        return 0, report
    except (OSError, ProjectError, ValueError) as error:
        report.update({"ok": False, "error": str(error)})
        return 2, report


def load_project_manifest(target: Path) -> dict[str, Any]:
    path = target / MANIFEST_PATH
    if not path.is_file():
        raise ProjectError(f"project is not initialized: {path}")
    return read_project_manifest(path)


def command_refresh(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    target = args.target.resolve()
    report = base_report("project-refresh", target)
    try:
        ensure_target(target)
        manifest = load_project_manifest(target)
        requested = args.discovery
        mode = manifest.get("discovery", {}).get("default_adapter", "local") if requested == "auto" else requested
        report["discovery_mode"] = mode
        ok = refresh_projection(target, args, mode, manifest, report)
        report["ok"] = ok
        if not ok:
            report["error"] = f"{mode} project discovery failed"
        return (0 if ok else 1), report
    except (OSError, ProjectError, ValueError) as error:
        report.update({"ok": False, "error": str(error)})
        return 2, report


def block_body(content: str) -> str | None:
    if content.count(PROJECT_AGENTS_START) != 1 or content.count(PROJECT_AGENTS_END) != 1:
        return None
    start = content.find(PROJECT_AGENTS_START)
    end = content.find(PROJECT_AGENTS_END, start)
    if end < start:
        return None
    return content[start:end + len(PROJECT_AGENTS_END)]


def command_doctor(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    target = args.target.resolve()
    report = base_report("project-doctor", target)
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    try:
        ensure_target(target)
        manifest = load_project_manifest(target)
        checks.append({"name": "manifest", "ok": True, "project_id": manifest["project_id"]})
        verification, expected_lock = install_rules(
            source_root() / RULE_SOURCE,
            target,
            dry_run=True,
        )
        lock = target / RULE_DESTINATION / ".bundle-lock.json"
        lock_value = read_json(lock, LOCK_SCHEMA_VERSION) if lock.is_file() else {}
        drift = sorted(
            verification.created
            + verification.updated
            + verification.candidates
            + verification.orphans
        )
        rule_root = target / RULE_DESTINATION
        allowed_rule_files = set(expected_lock.get("desired_files", {})) | {".bundle-lock.json"}
        for conflict in lock_value.get("conflicts", []):
            try:
                allowed_rule_files.add(
                    (target / str(conflict)).relative_to(rule_root).as_posix()
                )
            except ValueError:
                drift.append(str(conflict))
        if rule_root.is_dir():
            for rule_path in sorted(rule_root.rglob("*")):
                relative_rule = rule_path.relative_to(rule_root).as_posix()
                if rule_path.is_symlink():
                    drift.append(relative_rule)
                elif rule_path.is_file() and relative_rule not in allowed_rule_files:
                    drift.append(relative_rule)
        drift = sorted(set(drift))
        lock_ok = (
            lock.is_file()
            and lock_value.get("bundle_id") == BUNDLE_ID
            and lock_value.get("bundle_sha256") == expected_lock.get("bundle_sha256")
            and lock_value.get("desired_files") == expected_lock.get("desired_files")
        )
        bundle_ok = not drift and lock_ok
        if not bundle_ok:
            errors.append("Platform rule bundle is missing, modified, stale, or has unresolved conflicts")
        checks.append(
            {
                "name": "rule-bundle-integrity",
                "ok": bundle_ok,
                "path": str(lock),
                "drift": drift,
            }
        )
        rule_index = target / RULE_DESTINATION / "index.md"
        if not rule_index.is_file():
            errors.append(f"platform rule index missing: {rule_index}")
        checks.append({"name": "rule-index", "ok": rule_index.is_file(), "path": str(rule_index)})
        legacy_rule_references: list[str] = []
        if rule_root.is_dir():
            for rule_file in sorted(rule_root.rglob("*.md")):
                if rule_file.is_symlink():
                    continue
                lowered = rule_file.read_text(encoding="utf-8", errors="replace").lower()
                if ".trellis/" in lowered or "trellis task" in lowered or "trellis workflow" in lowered:
                    legacy_rule_references.append(rule_file.relative_to(target).as_posix())
        if legacy_rule_references:
            errors.append("Active platform rules still contain Trellis runtime references")
        checks.append(
            {
                "name": "rule-independence",
                "ok": not legacy_rule_references,
                "paths": legacy_rule_references,
            }
        )
        knowledge_index = target / KNOWLEDGE_INDEX_PATH
        if not knowledge_index.is_file():
            errors.append(f"knowledge index missing: {knowledge_index}")
        else:
            read_json(knowledge_index, KNOWLEDGE_SCHEMA_VERSION)
        checks.append({"name": "knowledge-index", "ok": knowledge_index.is_file(), "path": str(knowledge_index)})
        agents = target / "AGENTS.md"
        content = agents.read_text(encoding="utf-8") if agents.is_file() else ""
        body = block_body(content)
        agents_ok = body is not None and ".trellis" not in body.lower() and "trellis" not in body.lower()
        if not agents_ok:
            errors.append("AGENTS.md platform block is missing, malformed, or still references Trellis")
        checks.append({"name": "project-agents", "ok": agents_ok, "path": str(agents)})
        conflicts = lock_value.get("conflicts", [])
        if conflicts:
            warnings.append("Platform rule candidates require review")
        if (target / ".trellis").exists():
            warnings.append("Legacy .trellis projection is present but inactive")
        report.update(
            {
                "ok": not errors,
                "checks": checks,
                "errors": errors,
                "warnings": warnings,
            }
        )
        return (0 if not errors else 2), report
    except (OSError, ProjectError, ValueError) as error:
        report.update({"ok": False, "error": str(error), "checks": checks})
        return 2, report


def migration_destination(target: Path, source: Path, trellis: Path) -> Path | None:
    relative = source.relative_to(trellis)
    parts = relative.parts
    if parts[:2] == ("spec", "project"):
        return target / CONTEXT_PATH / Path(*parts[2:])
    if parts[:2] == ("knowledge", "project"):
        return target / KNOWLEDGE_PATH / "project" / Path(*parts[2:])
    if parts and parts[0] == "spec":
        rule_path = Path(*parts[1:])
        if rule_path.as_posix() in LEGACY_PLATFORM_RULE_PATHS:
            return target / KNOWLEDGE_PATH / "legacy-trellis-spec" / rule_path
        return target / PROJECTION_ROOT / "rules" / "project" / rule_path
    return None


def plan_migration_file(source: Path, destination: Path, target: Path) -> tuple[str, Path, bytes | None]:
    validate_output_path(target, destination)
    content = source.read_bytes()
    if not destination.exists():
        return "created", destination, content
    if not destination.is_file() or destination.is_symlink():
        raise ProjectError(f"migration destination is not a regular file: {destination}")
    if destination.read_bytes() == content:
        return "skipped", destination, None
    candidate = destination.with_name(f"{destination.name}.trellis.new")
    validate_output_path(target, candidate)
    if candidate.exists():
        if not candidate.is_file() or candidate.is_symlink():
            raise ProjectError(f"migration candidate is not a regular file: {candidate}")
        if candidate.read_bytes() != content:
            raise ProjectError(f"migration candidate contains different content: {candidate}")
        return "candidate", candidate, None
    return "candidate", candidate, content


def command_migrate_trellis(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    target = args.target.resolve()
    report = base_report("migrate-trellis", target)
    try:
        ensure_target(target)
        trellis = target / ".trellis"
        if not trellis.is_dir() or trellis.is_symlink():
            raise ProjectError(f"legacy Trellis projection not found: {trellis}")
        args.discovery = "skip"
        mode = "skip"

        planned: list[tuple[str, Path, bytes | None, Path]] = []
        ignored: list[str] = []
        for source in sorted(trellis.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            destination = migration_destination(target, source, trellis)
            if destination is None:
                ignored.append(source.relative_to(target).as_posix())
                continue
            action, write_path, content = plan_migration_file(source, destination, target)
            planned.append((action, write_path, content, source))

        # Validate project-owned files and the rule bundle before committing migration output.
        _, _, _ = plan_project_agents(target)
        manifest = install_projection(target, args, mode, report)
        migrated: list[dict[str, Any]] = []
        migration_state: list[dict[str, Any]] = []
        for action, destination, content, source in planned:
            if content is not None:
                atomic_write_bytes(destination, content, args.dry_run, root=target)
            item = {
                "source": source.relative_to(target).as_posix(),
                "destination": destination.relative_to(target).as_posix(),
                "action": action,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            migrated.append(item)
            migration_state.append(
                {
                    "source": item["source"],
                    "destination": item["destination"],
                    "status": "conflict_candidate" if action == "candidate" else "present",
                    "sha256": item["sha256"],
                }
            )
        legacy_only = {
            "workflow": (trellis / "workflow.md").is_file(),
            "tasks": (trellis / "tasks").is_dir(),
            "agents": (trellis / "agents").is_dir(),
            "paths": ignored,
        }
        migration_value = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "source": ".trellis",
            "source_preserved": True,
            "active_rules_source": BUNDLE_ID,
            "migrated": migration_state,
            "legacy_only": legacy_only,
        }
        migration_changed = atomic_write_bytes(
            target / MIGRATION_REPORT_PATH,
            json_bytes(migration_value),
            args.dry_run,
            root=target,
        )
        report["steps"].append(
            {
                "name": "trellis-content-migration",
                "ok": True,
                "changed": migration_changed or any(item[2] is not None for item in planned),
                "files": migrated,
                "legacy_only": legacy_only,
                "source_preserved": True,
                "dry_run": args.dry_run,
            }
        )
        report["steps"].append(write_knowledge_index(target, manifest, args.dry_run))
        report["ok"] = True
        return 0, report
    except (OSError, ProjectError, ValueError) as error:
        report.update({"ok": False, "error": str(error)})
        return 2, report


def add_init_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", type=Path)
    parser.add_argument("--discovery", choices=("auto", "windows", "local", "skip"), default="auto")
    parser.add_argument("--project-id")
    parser.add_argument("--windows-human-workspace")
    parser.add_argument("--windows-agent-workspace", "--windows-workspace", dest="windows_agent_workspace")
    parser.add_argument("--sync-mode", choices=("git",), default="git")
    parser.add_argument("--keil-project", "--mcu-keil-project", dest="mcu_keil_project")
    parser.add_argument("--build-knowledge", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-git-exclude", action="store_true")
    parser.add_argument("--overwrite-rules", action="store_true", help=argparse.SUPPRESS)


def parse_args(argv: list[str]) -> argparse.Namespace:
    json_requested = "--json" in argv
    argv = [argument for argument in argv if argument != "--json"]
    parser = argparse.ArgumentParser(prog="embedded-project", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {platform_version()}",
    )
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    add_init_arguments(init)
    init.set_defaults(func=command_init)

    refresh = sub.add_parser("refresh")
    refresh.add_argument("target", type=Path)
    refresh.add_argument("--discovery", choices=("auto", "windows", "local", "skip"), default="auto")
    refresh.add_argument("--keil-project", "--mcu-keil-project", dest="mcu_keil_project")
    refresh.add_argument("--build-knowledge", action="store_true")
    refresh.add_argument("--dry-run", action="store_true")
    refresh.add_argument("--no-git-exclude", action="store_true", help=argparse.SUPPRESS)
    refresh.set_defaults(overwrite_rules=False)
    refresh.set_defaults(func=command_refresh)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("target", type=Path)
    doctor.set_defaults(func=command_doctor)

    migrate = sub.add_parser("migrate-trellis")
    migrate.add_argument("target", type=Path)
    migrate.add_argument("--project-id")
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--no-git-exclude", action="store_true")
    migrate.add_argument("--overwrite-rules", action="store_true", help=argparse.SUPPRESS)
    migrate.set_defaults(
        discovery="skip",
        windows_human_workspace=None,
        windows_agent_workspace=None,
        sync_mode="git",
        mcu_keil_project=None,
        build_knowledge=False,
    )
    migrate.set_defaults(func=command_migrate_trellis)

    args = parser.parse_args(argv)
    args.json = json_requested or args.json
    return args


def emit(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        stream = sys.stdout if report.get("ok") else sys.stderr
        print(json.dumps(report, ensure_ascii=False, indent=2), file=stream)
        return
    if report.get("ok"):
        print(f"{report['operation']} complete: {report['target']}")
    else:
        print(f"error: {report.get('error', report['operation'] + ' failed')}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    code, report = args.func(args)
    emit(report, args.json)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
