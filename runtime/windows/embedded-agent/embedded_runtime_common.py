"""Windows-local embedded agent.

This CLI owns Windows project background, discovery, build/log bridge calls and
device-operation gates. Authorized local or remote Agents consume its JSON
Interface instead of constructing toolchain-specific commands.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat as stat_module
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from embedded_runtime_contract import (
    CAPABILITY_CONTRACT_VERSION,
    CAPABILITY_RESULT_SCHEMA_VERSION,
    capability_result,
    contract_now_iso,
)


SCHEMA_VERSION = "embedded-project-background/v1"
DEFAULT_INSTALL_ROOT = Path(
    os.environ.get("EMBEDDED_AGENT_INSTALL_ROOT")
    or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EmbeddedAgentPlatform"
)
DEFAULT_ROOT = Path(os.environ.get("EMBEDDED_AGENT_ROOT", str(DEFAULT_INSTALL_ROOT / "state")))
RUNTIME_SOURCE_HOME = Path(__file__).resolve().parents[1]
# Executable Python backends are code, not configuration. Keep their locations
# anchored to the installed Runtime tree so environment variables and public CLI
# arguments cannot select another script.
DEFAULT_AGENTCTL = RUNTIME_SOURCE_HOME / "bin" / "agentctl.py"
DEFAULT_SDK_MANAGER = RUNTIME_SOURCE_HOME / "bin" / "sdk-manager.py"
DEFAULT_SDK_STORE = Path(os.environ.get("EMBEDDED_SDK_STORE", str(DEFAULT_INSTALL_ROOT / "sdk")))
DEFAULT_SDK_LOCK = Path(os.environ.get("EMBEDDED_SDK_LOCK", str(DEFAULT_INSTALL_ROOT / "sdk.lock")))
DEFAULT_WORKSPACE_ROOT = Path(os.environ.get("EMBEDDED_AGENT_WORKSPACE_ROOT", str(DEFAULT_INSTALL_ROOT / "workspaces")))
FINGERPRINT_SUFFIXES = {".uvprojx", ".uvproj", ".uvoptx", ".ps1", ".sh", ".cmake"}
FINGERPRINT_NAMES = {"CMakeLists.txt", "Makefile", "makefile", "build.sh", "build.ps1"}
IGNORE_DIRS = {".git", ".trellis", ".embedded-agent", "build", "out", "dist", "__pycache__", "node_modules"}
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "cp936")
SMALL_HASH_LIMIT = 16 * 1024 * 1024
DEFAULT_READ_BYTES = 64 * 1024
DEFAULT_TAIL_BYTES = 1024 * 1024
DEFAULT_GIT_BYTES = 128 * 1024
DEFAULT_TOOL_SEARCH_BYTES = 1024 * 1024
MAX_TOOL_SEARCH_BYTES = 16 * 1024 * 1024
DEFAULT_LOG_IMPORT_MAX_BYTES = 32 * 1024 * 1024
MAX_LOG_IMPORT_BYTES = 64 * 1024 * 1024
DEFAULT_LOG_QUERY_BYTES = 4 * 1024 * 1024
MAX_LOG_QUERY_BYTES = 16 * 1024 * 1024
DEFAULT_GIT_TIMEOUT = 20
MAX_GIT_LIMIT = 200
MAX_SNIPPET_CHARS = 300
MAX_LOG_CONTEXT_LINES = 200
LOG_ARTIFACT_SCHEMA_VERSION = "embedded-log-artifact/v1"
RUNTIME_CONTRACT_VERSION = CAPABILITY_CONTRACT_VERSION
UNKNOWN_PLATFORM_VERSION = "unknown"
RUNTIME_MODULE_FILES = (
    "embedded_runtime_contract.py",
    "embedded_runtime_aboot.py",
    "embedded_runtime_cli.py",
    "embedded_runtime_can.py",
    "embedded_runtime_common.py",
    "embedded_runtime_device.py",
    "embedded_runtime_diagnose.py",
    "embedded_runtime_git.py",
    "embedded_runtime_jenkins.py",
    "embedded_runtime_knowledge.py",
    "embedded_runtime_operations.py",
    "embedded_runtime_sdk.py",
    "embedded_runtime_tools.py",
)


def _version_from_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?",
        value,
    ):
        return None
    return value


def platform_version() -> str:
    """Read the installed release version, with a source-checkout fallback."""
    installed = _version_from_file(RUNTIME_SOURCE_HOME / "VERSION")
    if installed is not None:
        return installed

    # When run directly from this repository RUNTIME_SOURCE_HOME is
    # <repo>/runtime/windows. Only use the ancestor fallback when the expected
    # source-tree marker exists, so an incomplete installation cannot pick up
    # an unrelated ancestor VERSION file.
    if len(RUNTIME_SOURCE_HOME.parents) > 1:
        repository_root = RUNTIME_SOURCE_HOME.parents[1]
        if (repository_root / "bootstrap" / "embedded_project.py").is_file():
            source = _version_from_file(repository_root / "VERSION")
            if source is not None:
                return source
    return UNKNOWN_PLATFORM_VERSION
ADB_TTY_NAME_PATTERN = re.compile(r"tty[A-Za-z0-9_.-]{1,63}\Z")
ADB_DEVICE_SERIAL_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
FAILURE_PATTERNS = [
    ("keil-error", re.compile(r"\b[LC]\d{4}E\b", re.IGNORECASE)),
    ("fatal-error", re.compile(r"\bfatal\s+error\b", re.IGNORECASE)),
    ("compiler-error", re.compile(r"\berror\s*[:#]|\berror\b", re.IGNORECASE)),
    ("linker-error", re.compile(r"\bundefined reference\b|\bunresolved external\b", re.IGNORECASE)),
    ("file-error", re.compile(r"\bcannot open\b|\bno such file\b", re.IGNORECASE)),
    ("runtime-failure", re.compile(r"\bfailed\b|\bfailure\b|\bexception\b|\btraceback\b|\bhardfault\b", re.IGNORECASE)),
]


@dataclass(frozen=True)

class AgentPaths:
    root: Path
    projects: Path
    jobs: Path
    workspace_root: Path


def background_target_name(target: str) -> str:
    """Map public build target names to the existing project-background schema."""
    return "mcu" if target == "keil" else target

def now_iso() -> str:
    return contract_now_iso()

def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

def print_result(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json_dump(value))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))

def result(
    ok: bool,
    operation: str,
    exit_code: int = 0,
    **fields: Any,
) -> dict[str, Any]:
    return capability_result(ok, operation, exit_code, timestamp=now_iso(), **fields)

def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None

PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_project_id(project: str) -> str:
    candidate = project.strip()
    stem = candidate.split(".", 1)[0].upper()
    if (
        not PROJECT_ID_PATTERN.fullmatch(candidate)
        or candidate in {".", ".."}
        or candidate.endswith(".")
        or stem in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError(
            "project id must be 1-128 ASCII letters, digits, dots, underscores, or "
            "hyphens; it must start with a letter or digit and not be a reserved name"
        )
    return candidate

def agent_paths(root: Path | None) -> AgentPaths:
    base = (root or DEFAULT_ROOT).resolve()
    default_root = DEFAULT_ROOT.expanduser().resolve()
    # The stable public launcher pins DEFAULT_ROOT, whose workspace boundary is
    # machine configuration.  Isolated test harnesses use a non-default state
    # root and deliberately keep their workspace beside it under root.parent.
    workspace_root = (
        DEFAULT_WORKSPACE_ROOT.expanduser()
        if _same_local_path(base, default_root)
        else base.parent
    )
    return AgentPaths(
        root=base,
        projects=base / "projects",
        jobs=base / "jobs",
        workspace_root=workspace_root,
    )

def project_dir(paths: AgentPaths, project: str) -> Path:
    return paths.projects / safe_project_id(project)

def background_path(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "background.json"

def background_md_path(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "background.md"

def runs_path(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "runs.jsonl"

def logs_dir(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "logs"

def knowledge_dir(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "knowledge"

def log_artifacts_dir(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "artifacts" / "logs"

def sdk_mappings_path(paths: AgentPaths, project: str) -> Path:
    return project_dir(paths, project) / "sdk-mappings.json"

def runtime_job_dir(paths: AgentPaths, job_id: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id):
        return None
    candidate = (paths.jobs / job_id).resolve()
    return candidate if is_relative_to(candidate, paths.jobs) else None

def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)

def path_kind(path: Path) -> str:
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    return "missing"

def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False

def is_lexically_relative_to(path: Path, root: Path) -> bool:
    """Check containment without following a controlled Junction or symlink."""
    try:
        normalized_path = os.path.normcase(os.path.abspath(os.fspath(path)))
        normalized_root = os.path.normcase(os.path.abspath(os.fspath(root)))
        return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
    except ValueError:
        return False

def configured_log_import_roots() -> list[Path]:
    configured = os.environ.get("EMBEDDED_AGENT_LOG_IMPORT_ROOTS", "")
    values = [value for value in configured.split(os.pathsep) if value.strip()]
    if not values:
        user_home = Path(os.environ.get("USERPROFILE") or Path.home())
        values = [str(user_home / "Desktop")]
    roots: list[Path] = []
    for value in values:
        try:
            roots.append(Path(value).expanduser().resolve())
        except OSError:
            roots.append(Path(value).expanduser().absolute())
    return roots

def is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def validated_workspace_output_path(
    workspace: Path,
    relative_path: Path,
    *,
    label: str = "Workspace output",
) -> Path:
    """Return a fixed workspace output path without following reparse points.

    The returned path may not exist yet. Every existing component from the
    workspace through the requested leaf is checked with ``lstat`` so a project
    cannot redirect Runtime writes through a symlink or Windows junction.
    """
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError(f"{label} must be a normalized workspace-relative path")

    try:
        lexical_workspace = Path(os.path.abspath(os.fspath(Path(workspace).expanduser())))
        workspace_stat = lexical_workspace.lstat()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{label} workspace is unavailable: {exc}") from exc
    if is_reparse_point(lexical_workspace) or not stat_module.S_ISDIR(workspace_stat.st_mode):
        raise ValueError(f"{label} workspace must be a real directory, not a symlink or reparse point")
    for component in lexical_workspace.parents:
        if is_reparse_point(component):
            raise ValueError(f"{label} must not traverse a symlink or reparse point: {component}")
    try:
        canonical_workspace = lexical_workspace.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{label} workspace cannot be resolved: {exc}") from exc
    if not _same_local_path(lexical_workspace, canonical_workspace):
        raise ValueError(f"{label} workspace must already be canonical: {lexical_workspace}")

    candidate = canonical_workspace.joinpath(relative)
    current = canonical_workspace
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            item_stat = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"{label} cannot inspect path component {current}: {exc}") from exc
        if is_reparse_point(current):
            raise ValueError(f"{label} must not traverse a symlink or reparse point: {current}")
        if index < len(relative.parts) - 1 and not stat_module.S_ISDIR(item_stat.st_mode):
            raise ValueError(f"{label} parent is not a directory: {current}")

    try:
        canonical_candidate = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{label} cannot be resolved: {exc}") from exc
    if (
        not is_lexically_relative_to(canonical_candidate, canonical_workspace)
        or not _same_local_path(candidate, canonical_candidate)
    ):
        raise ValueError(f"{label} escapes the registered workspace: {candidate}")
    return candidate


def ensure_workspace_output_directory(
    workspace: Path,
    relative_path: Path,
    *,
    label: str = "Workspace output directory",
) -> Path:
    """Create a workspace output directory one checked component at a time."""
    destination = validated_workspace_output_path(
        workspace,
        relative_path,
        label=label,
    )
    canonical_workspace = Path(os.path.abspath(os.fspath(Path(workspace).expanduser()))).resolve(
        strict=True
    )
    relative = destination.relative_to(canonical_workspace)
    current = canonical_workspace
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            item_stat = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise ValueError(f"{label} cannot create directory {current}: {exc}") from exc
            try:
                item_stat = current.lstat()
            except OSError as exc:
                raise ValueError(f"{label} cannot inspect created directory {current}: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"{label} cannot inspect directory {current}: {exc}") from exc
        if is_reparse_point(current):
            raise ValueError(f"{label} must not traverse a symlink or reparse point: {current}")
        if not stat_module.S_ISDIR(item_stat.st_mode):
            raise ValueError(f"{label} path component is not a directory: {current}")
        validated_workspace_output_path(
            canonical_workspace,
            Path(*relative.parts[: index + 1]),
            label=label,
        )
    return validated_workspace_output_path(
        canonical_workspace,
        relative,
        label=label,
    )


def is_safe_tree_directory(path: Path, root: Path) -> bool:
    """Return true only for a real directory contained by the scanned tree."""
    try:
        item_stat = path.lstat()
        canonical = path.resolve(strict=True)
        canonical_root = root.resolve(strict=True)
    except OSError:
        return False
    return (
        not is_reparse_point(path)
        and stat_module.S_ISDIR(item_stat.st_mode)
        and is_lexically_relative_to(canonical, canonical_root)
    )

def resolve_managed_workspace(
    value: str | Path,
    *,
    must_exist: bool,
    workspace_root: Path | None = None,
) -> tuple[Path | None, str | None]:
    """Resolve a project workspace below its configured workspace root."""
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        return None, "Workspace must be an absolute path"
    configured = (workspace_root or DEFAULT_WORKSPACE_ROOT).expanduser()
    configured_lexical = Path(os.path.abspath(configured))
    requested_lexical = Path(os.path.abspath(requested))
    try:
        configured_root = configured_lexical.resolve(strict=False)
        workspace = requested_lexical.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        return None, f"Workspace cannot be resolved: {exc}"
    if not is_lexically_relative_to(workspace, configured_root):
        return None, f"Workspace is outside the configured workspace root: {configured_root}"
    if configured_lexical.exists() and (
        is_reparse_point(configured_lexical) or not configured_lexical.is_dir()
    ):
        return None, "Configured workspace root must be a real directory, not a reparse point"
    try:
        relative = requested_lexical.relative_to(configured_lexical)
    except ValueError:
        return None, f"Workspace is outside the configured workspace root: {configured_root}"
    current = configured_lexical
    for part in relative.parts:
        current = current / part
        if current.exists() and is_reparse_point(current):
            return None, f"Workspace must not traverse a symlink or reparse point: {current}"
    if must_exist and not workspace.is_dir():
        return None, "Workspace does not exist or is not a directory"
    return workspace, None

def _same_local_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(
        os.path.abspath(os.fspath(right))
    )

def _validate_runtime_owned_python(
    candidate: Path,
    relative_path: str,
    label: str,
) -> tuple[Path | None, str | None]:
    """Resolve an exact, non-reparse Python resource in the Runtime tree."""
    expected = RUNTIME_SOURCE_HOME / Path(relative_path)
    if not _same_local_path(candidate, expected):
        return None, f"{label} is not the Runtime-owned resource: {expected}"
    try:
        parent_stat = expected.parent.lstat()
        resource_stat = expected.lstat()
        resolved = expected.resolve(strict=True)
    except FileNotFoundError:
        return None, f"{label} capability unavailable: Runtime-owned resource is not installed"
    except OSError as exc:
        return None, f"{label} capability unavailable: cannot inspect Runtime-owned resource: {exc}"
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    parent_reparse = expected.parent.is_symlink() or bool(
        getattr(parent_stat, "st_file_attributes", 0) & reparse_flag
    )
    resource_reparse = expected.is_symlink() or bool(
        getattr(resource_stat, "st_file_attributes", 0) & reparse_flag
    )
    if parent_reparse or not stat_module.S_ISDIR(parent_stat.st_mode):
        return None, f"{label} capability unavailable: Runtime resource directory is not trusted"
    if resource_reparse or not stat_module.S_ISREG(resource_stat.st_mode):
        return None, f"{label} capability unavailable: Runtime-owned resource must be a regular non-symlink file"
    if not _same_local_path(resolved, expected) or not _same_local_path(resolved.parent, expected.parent):
        return None, f"{label} capability unavailable: Runtime-owned resource escapes its trusted directory"
    return resolved, None

def trusted_agentctl() -> tuple[Path | None, str | None]:
    return _validate_runtime_owned_python(DEFAULT_AGENTCTL, "bin/agentctl.py", "Agent control backend")

def trusted_sdk_manager() -> tuple[Path | None, str | None]:
    return _validate_runtime_owned_python(DEFAULT_SDK_MANAGER, "bin/sdk-manager.py", "SDK Manager")

def valid_log_identifier(value: str, maximum: int) -> bool:
    return bool(re.fullmatch(rf"[A-Za-z0-9][A-Za-z0-9_.-]{{0,{maximum - 1}}}", value))

def resolve_log_import_source(value: str) -> tuple[Path | None, dict[str, Any], str | None]:
    candidate = Path(value).expanduser()
    roots = configured_log_import_roots()
    info = {
        "input_path": value,
        "allowed_roots": [str(root) for root in roots],
    }
    if not candidate.is_absolute():
        return None, info, "Log source must be an absolute path"
    if is_reparse_point(candidate):
        return None, info, "Log source must not be a symlink or reparse point"
    try:
        normalized = candidate.resolve(strict=True)
    except OSError:
        return None, info, "Log source does not exist or cannot be resolved"
    info["normalized_path"] = str(normalized)
    if not any(is_relative_to(normalized, root) for root in roots):
        return None, info, "Log source is outside the configured import roots"
    if not normalized.is_file():
        return None, info, "Log source is not a file"
    return normalized, info, None

def log_objects_dir(paths: AgentPaths, project: str) -> Path:
    return log_artifacts_dir(paths, project) / "objects"

def log_records_dir(paths: AgentPaths, project: str) -> Path:
    return log_artifacts_dir(paths, project) / "records"

def log_artifact_id(task: str, label: str, digest: str) -> str:
    return f"log-{task}-{label}-{digest[:16]}"

def log_record_path(paths: AgentPaths, project: str, artifact_id: str) -> Path | None:
    if not valid_log_identifier(artifact_id, 180):
        return None
    root = log_records_dir(paths, project)
    candidate = (root / f"{artifact_id}.json").resolve()
    return candidate if is_relative_to(candidate, root) else None

def load_log_artifact(paths: AgentPaths, project: str, artifact_id: str) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    record_path = log_record_path(paths, project, artifact_id)
    if record_path is None:
        return None, None, "Invalid log artifact id"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, "Log artifact record was not found"
    if not isinstance(record, dict) or record.get("schema_version") != LOG_ARTIFACT_SCHEMA_VERSION:
        return None, None, "Log artifact record is invalid"
    content_rel = record.get("content_path")
    if not isinstance(content_rel, str) or not content_rel:
        return None, None, "Log artifact record has no content path"
    root = log_artifacts_dir(paths, project)
    objects = log_objects_dir(paths, project)
    content = (root / content_rel).resolve()
    if not is_relative_to(content, objects) or not content.is_file():
        return None, None, "Log artifact content is missing or invalid"
    return record, content, None

def resolve_tool_path(background: dict[str, Any], value: str | None, default: str = ".") -> dict[str, Any]:
    workspace = Path(background["workspace"]).resolve()
    raw = value if value not in (None, "") else default
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        normalized = candidate.resolve()
    except OSError:
        normalized = candidate.absolute()
    return {
        "input_path": raw,
        "path": normalized,
        "normalized_path": str(normalized),
        "project_path": rel(normalized, workspace),
        "exists": normalized.exists(),
        "kind": path_kind(normalized),
        "inside_workspace": is_relative_to(normalized, workspace),
    }

def resolve_sdk_target(workspace: Path, value: str) -> dict[str, Any]:
    """Resolve a mapping destination without treating its SDK link as an escape."""
    raw = value
    workspace = Path(os.path.abspath(os.fspath(workspace)))
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    target = Path(os.path.abspath(os.fspath(candidate)))
    inside_workspace = is_lexically_relative_to(target, workspace)
    resolved = target.resolve() if target.exists() else None
    project_path = os.path.relpath(target, workspace).replace("\\", "/") if inside_workspace else str(target)
    return {
        "input_path": raw,
        "path": target,
        "normalized_path": str(target),
        "resolved_path": str(resolved) if resolved else None,
        "project_path": project_path,
        "exists": target.exists(),
        "kind": path_kind(target),
        "inside_workspace": inside_workspace,
    }

def validate_non_reparse_ancestors(root: Path, target: Path) -> tuple[Path | None, str | None]:
    """Reject existing reparse ancestors while intentionally excluding the leaf.

    SDK mappings may themselves be managed Junctions, so resolving the complete
    destination would incorrectly classify a valid mapping as a workspace escape.
    Walking the lexical parent chain catches an attacker-controlled ancestor
    without changing the check/replace semantics of the destination itself.
    """
    root = Path(os.path.abspath(os.fspath(root)))
    target = Path(os.path.abspath(os.fspath(target)))
    if not is_lexically_relative_to(target, root):
        return root, "Path is outside the trusted root"
    try:
        relative = target.relative_to(root)
    except ValueError:
        return root, "Path is outside the trusted root"

    ancestors = [root]
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        ancestors.append(current)

    for index, ancestor in enumerate(ancestors):
        try:
            ancestor_stat = ancestor.lstat()
        except FileNotFoundError:
            if index == 0:
                return ancestor, "Trusted root does not exist"
            break
        except OSError as exc:
            return ancestor, f"Cannot inspect path ancestor: {exc}"
        if is_reparse_point(ancestor):
            return ancestor, "Path must not traverse a symlink or reparse point"
        if not stat_module.S_ISDIR(ancestor_stat.st_mode):
            return ancestor, "Path ancestor is not a directory"
    return None, None

def fail_outside_workspace(operation: str, background: dict[str, Any], info: dict[str, Any], as_json: bool) -> int:
    value = result(
        False,
        operation,
        5,
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        inside_workspace=False,
        first_failure="Path is outside project workspace",
    )
    print_result(value, as_json)
    return 5

def decode_text(data: bytes, requested: str = "auto") -> tuple[str | None, str, bool]:
    if requested and requested != "auto":
        try:
            return data.decode(requested), requested, False
        except UnicodeDecodeError:
            return None, requested, True
    if b"\x00" in data:
        return None, "binary", True
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding), encoding, False
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace", False

def read_text_file(path: Path, encoding: str = "auto", max_bytes: int | None = None) -> tuple[str | None, str, bool, int]:
    try:
        if max_bytes is None:
            data = path.read_bytes()
        else:
            with path.open("rb") as handle:
                data = handle.read(max_bytes)
    except OSError:
        return None, "unknown", False, 0
    text, used_encoding, binary = decode_text(data, encoding)
    return text, used_encoding, binary, len(data)

def bounded_text(value: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    value = value.replace("\r", "")
    if len(value) <= limit:
        return value
    return value[:limit] + "..."

def bounded_output(value: str | bytes | None, max_bytes: int) -> tuple[str, int, bool]:
    if value is None:
        return "", 0, False
    if isinstance(value, bytes):
        data = value
    else:
        data = value.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        text, _, binary = decode_text(data)
        if binary or text is None:
            text = data.decode("utf-8", errors="replace")
        return text, len(data), False
    trimmed = data[:max(1, max_bytes)]
    text, _, binary = decode_text(trimmed)
    if binary or text is None:
        text = trimmed.decode("utf-8", errors="replace")
    return text, len(data), True

def file_metadata(path: Path, include_hash: bool = False) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "kind": "missing"}
    value: dict[str, Any] = {
        "exists": True,
        "kind": path_kind(path),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
        "readonly": not os.access(path, os.W_OK),
    }
    if path.is_file() and (include_hash or stat.st_size <= SMALL_HASH_LIMIT):
        value["sha256"] = sha256_file(path)
    return value

def copy_log_source(source: Path, destination: Path, max_bytes: int) -> tuple[dict[str, Any] | None, str | None]:
    try:
        before = source.stat()
    except OSError:
        return None, "Cannot stat log source"
    if before.st_size > max_bytes:
        return None, f"Log source exceeds the {max_bytes}-byte import limit"

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    digest = hashlib.sha256()
    size = 0
    newline_count = 0
    last_byte = b""
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                size += len(chunk)
                if size > max_bytes:
                    return None, f"Log source exceeds the {max_bytes}-byte import limit"
                writer.write(chunk)
                digest.update(chunk)
                newline_count += chunk.count(b"\n")
                if chunk:
                    last_byte = chunk[-1:]
        after = source.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or size != before.st_size:
            return None, "Log source changed during import"
        actual_sha256 = digest.hexdigest()
        already_present = destination.exists()
        if already_present:
            existing_sha256 = sha256_file(destination)
            if existing_sha256 != actual_sha256:
                return None, "Log artifact object collision"
        else:
            os.replace(temporary, destination)
        return {
            "size": size,
            "sha256": actual_sha256,
            "line_count": newline_count + (1 if size and last_byte != b"\n" else 0),
            "mtime": datetime.fromtimestamp(before.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
            "already_present": already_present,
        }, None
    except OSError as exc:
        return None, f"Cannot import log source: {exc}"
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

def bounded_entries(path: Path, max_entries: int) -> tuple[list[dict[str, Any]], int, bool]:
    try:
        children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError:
        return [], 0, False
    entries: list[dict[str, Any]] = []
    for child in children[:max_entries]:
        meta = file_metadata(child, include_hash=False)
        entries.append({
            "name": child.name,
            "path": child.as_posix(),
            "kind": meta.get("kind"),
            "size": meta.get("size"),
            "mtime": meta.get("mtime"),
            "readonly": meta.get("readonly"),
        })
    return entries, len(children), len(children) > max_entries

def iter_tool_files(root: Path) -> list[Path]:
    """Return regular files without crossing a symlink or reparse boundary."""
    try:
        root_stat = root.lstat()
    except OSError:
        return []
    if is_reparse_point(root):
        return []
    try:
        canonical_root = root.resolve(strict=True)
    except OSError:
        return []
    if stat_module.S_ISREG(root_stat.st_mode):
        return [canonical_root]
    if not stat_module.S_ISDIR(root_stat.st_mode):
        return []

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(canonical_root, followlinks=False):
        base = Path(dirpath)
        try:
            base_stat = base.lstat()
            resolved_base = base.resolve(strict=True)
        except OSError:
            dirnames[:] = []
            continue
        if (
            is_reparse_point(base)
            or not stat_module.S_ISDIR(base_stat.st_mode)
            or not is_lexically_relative_to(resolved_base, canonical_root)
        ):
            dirnames[:] = []
            continue

        safe_directories: list[str] = []
        for dirname in dirnames:
            if dirname in IGNORE_DIRS or dirname.startswith("."):
                continue
            candidate = base / dirname
            try:
                candidate_stat = candidate.lstat()
                resolved_candidate = candidate.resolve(strict=True)
            except OSError:
                continue
            if (
                is_reparse_point(candidate)
                or not stat_module.S_ISDIR(candidate_stat.st_mode)
                or not is_lexically_relative_to(resolved_candidate, canonical_root)
            ):
                continue
            safe_directories.append(dirname)
        dirnames[:] = safe_directories

        for filename in filenames:
            candidate = base / filename
            try:
                candidate_stat = candidate.lstat()
                resolved_candidate = candidate.resolve(strict=True)
            except OSError:
                continue
            if (
                is_reparse_point(candidate)
                or not stat_module.S_ISREG(candidate_stat.st_mode)
                or not is_lexically_relative_to(resolved_candidate, canonical_root)
            ):
                continue
            files.append(resolved_candidate)
    return sorted(files, key=lambda item: str(item).lower())

def detect_first_failure(lines: list[str]) -> dict[str, Any]:
    for index, line in enumerate(lines, start=1):
        for name, pattern in FAILURE_PATTERNS:
            if pattern.search(line):
                return {
                    "first_failure": line.strip(),
                    "line": index,
                    "pattern": name,
                    "patterns_checked": [item[0] for item in FAILURE_PATTERNS],
                }
    return {
        "first_failure": None,
        "line": None,
        "pattern": None,
        "patterns_checked": [item[0] for item in FAILURE_PATTERNS],
    }

def iter_files(root: Path) -> list[Path]:
    return iter_tool_files(root)

def parse_manifest(path: Path) -> list[dict[str, str]]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    projects: list[dict[str, str]] = []
    for elem in root.iter():
        if elem.tag.split("}")[-1] != "project":
            continue
        projects.append({
            "name": elem.get("name", ""),
            "path": elem.get("path", ""),
            "revision": elem.get("revision", "master"),
            "remote": elem.get("remote", ""),
        })
    return projects

def xml_text(root: ET.Element, tag: str) -> str | None:
    elem = root.find(f".//{tag}")
    if elem is None or not elem.text:
        return None
    return elem.text.strip()

def parse_keil_registry(name: str) -> dict[str, Any]:
    value: dict[str, Any] = {}
    serial = re.search(r"(?:^|\s)-U(\d+)(?:\s|$)", name)
    speed = re.search(r"(?:^|\s)-ZTIFSpeedSel(\d+)(?:\s|$)", name)
    debug_port = re.search(r'-N\d+\("([^"]*SW-DP[^"]*)"\)', name, re.IGNORECASE)
    dpidr = re.search(r"(?:^|\s)-D\d+\(([0-9A-Fa-f]+)\)", name)
    work_ram_start = re.search(r"(?:^|\s)-FD([0-9A-Fa-f]+)(?:\s|$)", name)
    work_ram_size = re.search(r"(?:^|\s)-FC([0-9A-Fa-f]+)(?:\s|$)", name)
    if serial:
        value["probe_serial"] = serial.group(1)
    if speed:
        value["speed_khz"] = int(speed.group(1))
    if debug_port:
        value["interface"] = "SWD"
        value["debug_port"] = debug_port.group(1)
    if dpidr:
        value["dpidr"] = f"0x{dpidr.group(1).upper()}"
    if work_ram_start or work_ram_size:
        value["flash_work_ram"] = {
            "start": f"0x{work_ram_start.group(1).upper()}" if work_ram_start else None,
            "size": f"0x{work_ram_size.group(1).upper()}" if work_ram_size else None,
        }

    algorithms: list[dict[str, Any]] = []
    for match in re.finditer(r"(?:^|\s)-FF(\d+)([^\s]+)", name):
        index, algorithm_name = match.groups()
        start = re.search(rf"(?:^|\s)-FS{index}([0-9A-Fa-f]+)(?:\s|$)", name)
        length = re.search(rf"(?:^|\s)-FL{index}([0-9A-Fa-f]+)(?:\s|$)", name)
        file_path = re.search(rf"(?:^|\s)-FP{index}\(([^)]*)\)", name)
        algorithms.append({
            "index": int(index),
            "name": algorithm_name,
            "start": f"0x{start.group(1).upper()}" if start else None,
            "length": f"0x{length.group(1).upper()}" if length else None,
            "path": file_path.group(1) if file_path else None,
        })
    if algorithms:
        value["flash_algorithms"] = algorithms
    return value

def parse_keil_user_options(path: Path, workspace: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {"path": rel(path, workspace), "parse_status": "invalid"}
    monitor = xml_text(root, "pMon")
    registry_entries: list[dict[str, str]] = []
    for entry in root.findall(".//SetRegEntry"):
        key = xml_text(entry, "Key")
        name = xml_text(entry, "Name")
        if key and name:
            registry_entries.append({"key": key, "name": name})
    effective_key = "JL2CM3" if monitor and "JL2CM3" in monitor.upper() else None
    effective = (
        next((item for item in registry_entries if item["key"].upper() == effective_key), None)
        if effective_key
        else None
    )
    stat = path.stat()
    value: dict[str, Any] = {
        "path": rel(path, workspace),
        "sha256": sha256_file(path),
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
        "parse_status": "ok",
        "monitor": monitor,
        "effective_registry_key": effective_key,
    }
    if effective:
        value.update(parse_keil_registry(effective["name"]))
    return value

def parse_keil(path: Path, workspace: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": rel(path, workspace)}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return info
    for tag, key in (
        ("Device", "device"),
        ("TargetName", "target"),
        ("OutputName", "output"),
        ("OutputDirectory", "output_directory"),
        ("FlashDriverDll", "flash_driver"),
        ("Flash2", "flash_driver_dll"),
    ):
        value = xml_text(root, tag)
        if value:
            info[key] = value
    create_executable = xml_text(root, "CreateExecutable")
    create_library = xml_text(root, "CreateLib")
    if create_executable in {"0", "1"}:
        info["create_executable"] = create_executable == "1"
    if create_library in {"0", "1"}:
        info["create_library"] = create_library == "1"
    if info.get("create_executable") is True and info.get("create_library") is not True:
        info["output_kind"] = "executable"
    elif info.get("create_library") is True and info.get("create_executable") is not True:
        info["output_kind"] = "library"
    else:
        info["output_kind"] = "unknown"
    if info.get("flash_driver"):
        info["project_flash"] = parse_keil_registry(info["flash_driver"])
    user_options = parse_keil_user_options(path.with_suffix(".uvoptx"), workspace)
    if user_options:
        info["user_options"] = user_options
    toolchain = root.find(".//Toolchain")
    if toolchain is not None:
        info["toolchain"] = toolchain.get("Name", "")
        info["toolchain_version"] = toolchain.get("Version", "")
    return info

def git_info(path: Path) -> dict[str, Any] | None:
    if not (path / ".git").exists():
        return None
    branch = run_simple(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"])
    commit = run_simple(["git", "-C", str(path), "rev-parse", "--short", "HEAD"])
    status = run_simple(["git", "-C", str(path), "status", "--short"])
    return {
        "path": str(path),
        "branch": branch,
        "commit": commit,
        "dirty": bool(status),
    }

def run_simple(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""

def git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_PAGER"] = "cat"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = env.get("LC_ALL", "C.UTF-8")
    return env

def run_git_read(
    repo: Path,
    git_args: list[str],
    max_bytes: int = DEFAULT_GIT_BYTES,
    timeout: int = DEFAULT_GIT_TIMEOUT,
) -> dict[str, Any]:
    command = ["git", "-C", str(repo), "--no-pager", *git_args]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(1, timeout),
            env=git_env(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_bytes, stdout_truncated = bounded_output(exc.stdout, max_bytes)
        stderr, stderr_bytes, stderr_truncated = bounded_output(exc.stderr, max_bytes)
        return {
            "ok": False,
            "exit_code": 124,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "truncated": stdout_truncated or stderr_truncated,
            "first_failure": f"git command timed out after {max(1, timeout)}s",
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "command": command,
            "stdout": "",
            "stderr": str(exc),
            "stdout_bytes": 0,
            "stderr_bytes": len(str(exc).encode("utf-8", errors="replace")),
            "truncated": False,
            "first_failure": str(exc),
        }
    stdout, stdout_bytes, stdout_truncated = bounded_output(completed.stdout, max_bytes)
    stderr, stderr_bytes, stderr_truncated = bounded_output(completed.stderr, max_bytes)
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "truncated": stdout_truncated or stderr_truncated,
        "first_failure": stderr.strip() if completed.returncode != 0 and stderr.strip() else None,
    }

def valid_clone_url(value: str) -> bool:
    """Allow network Git remotes without exposing shell or local-file access."""
    if not value or any(ch in value for ch in ("\r", "\n", "\x00")):
        return False
    if value.startswith(("file:", "\\\\", "/", "./", "../")):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    if value.startswith("git@"):
        return ":" in value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "ssh"} or not parsed.netloc or not parsed.path:
        return False
    if parsed.scheme in {"http", "https"} and parsed.username is not None:
        return False
    return parsed.password is None

def valid_http_server_url(value: str) -> bool:
    if not value or any(ch in value for ch in ("\r", "\n", "\x00")):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )

def clone_target(workspace: Path, value: str) -> tuple[Path | None, str | None]:
    raw = value.strip()
    if not raw or Path(raw).is_absolute():
        return None, "Clone target must be a relative path"
    candidate = (workspace / raw).resolve()
    if not is_relative_to(candidate, workspace):
        return None, "Clone target is outside workspace"
    return candidate, None

def resolve_git_root(background: dict[str, Any], value: str | None = ".") -> tuple[dict[str, Any], Path | None, dict[str, Any] | None]:
    info = resolve_tool_path(background, value)
    if not info["inside_workspace"]:
        return info, None, result(
            False,
            "git-root",
            5,
            project_id=background["project_id"],
            workspace=background["workspace"],
            input_path=info["input_path"],
            normalized_path=info["normalized_path"],
            inside_workspace=False,
            first_failure="Path is outside project workspace",
        )
    git_cwd = info["path"].parent if info["path"].is_file() else info["path"]
    probe = run_git_read(git_cwd, ["rev-parse", "--show-toplevel"], max_bytes=4096)
    if not probe["ok"]:
        return info, None, result(
            False,
            "git-root",
            probe["exit_code"],
            project_id=background["project_id"],
            workspace=background["workspace"],
            input_path=info["input_path"],
            normalized_path=info["normalized_path"],
            project_path=info["project_path"],
            inside_workspace=True,
            stderr=probe["stderr"],
            first_failure=probe["first_failure"] or "Path is not inside a Git repository",
        )
    repo = Path(probe["stdout"].strip()).resolve()
    workspace = Path(background["workspace"])
    if not is_relative_to(repo, workspace):
        return info, None, result(
            False,
            "git-root",
            5,
            project_id=background["project_id"],
            workspace=background["workspace"],
            input_path=info["input_path"],
            normalized_path=str(repo),
            inside_workspace=False,
            first_failure="Git repository root is outside project workspace",
        )
    return info, repo, None

def git_repo_context(background: dict[str, Any], repo: Path, info: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(background["workspace"])
    return {
        "project_id": background["project_id"],
        "workspace": background["workspace"],
        "input_path": info["input_path"],
        "normalized_path": info["normalized_path"],
        "project_path": info["project_path"],
        "repo_root": str(repo),
        "repo_path": rel(repo, workspace),
    }

def parse_porcelain_status(stdout: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for raw in stdout.splitlines():
        if not raw:
            continue
        if raw.startswith("## "):
            continue
        if raw.startswith("?? "):
            changes.append({"path": raw[3:], "index": "?", "worktree": "?", "status": "untracked"})
            continue
        if len(raw) < 4:
            changes.append({"path": raw.strip(), "index": "", "worktree": "", "status": "unknown"})
            continue
        index = raw[0]
        worktree = raw[1]
        path_text = raw[3:]
        item: dict[str, Any] = {
            "path": path_text,
            "index": index.strip() or " ",
            "worktree": worktree.strip() or " ",
            "status": porcelain_status_label(index, worktree),
        }
        if " -> " in path_text:
            old_path, new_path = path_text.split(" -> ", 1)
            item["old_path"] = old_path
            item["path"] = new_path
        changes.append(item)
    return changes

def porcelain_status_label(index: str, worktree: str) -> str:
    if index == "?" and worktree == "?":
        return "untracked"
    if index == "!" and worktree == "!":
        return "ignored"
    labels = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "U": "unmerged",
    }
    parts = []
    if index.strip():
        parts.append(f"index-{labels.get(index, index)}")
    if worktree.strip():
        parts.append(f"worktree-{labels.get(worktree, worktree)}")
    return ",".join(parts) if parts else "clean"

def parse_branch_status(stdout: str) -> dict[str, Any]:
    branch: dict[str, Any] = {}
    first = next((line for line in stdout.splitlines() if line.startswith("## ")), "")
    if not first:
        return branch
    text = first[3:]
    if "..." in text:
        local, rest = text.split("...", 1)
        branch["branch"] = local
        upstream = rest
        markers = ""
        if " [" in rest and rest.endswith("]"):
            upstream, markers = rest.rsplit(" [", 1)
            markers = markers.rstrip("]")
        branch["upstream"] = upstream
        for marker in markers.split(", "):
            if marker.startswith("ahead "):
                branch["ahead"] = int(marker.split(" ", 1)[1])
            elif marker.startswith("behind "):
                branch["behind"] = int(marker.split(" ", 1)[1])
    else:
        branch["branch"] = text
    branch.setdefault("ahead", 0)
    branch.setdefault("behind", 0)
    return branch

def git_short_value(repo: Path, git_args: list[str]) -> str | None:
    value = run_git_read(repo, git_args, max_bytes=4096)
    if not value["ok"]:
        return None
    text = value["stdout"].strip()
    return text or None

def classify_architecture(workspace: Path, manifests: list[dict[str, Any]]) -> str:
    joined = json.dumps(manifests, ensure_ascii=False).lower()
    workspace_text = str(workspace).replace("\\", "/").lower()
    has_mcu = is_safe_tree_directory(workspace / "mcu", workspace)
    has_mpu = is_safe_tree_directory(workspace / "mpu", workspace)
    if has_mcu and has_mpu:
        return "mcu-mpu"
    soc_markers = (
        "new_energy/top",
        "home/platform",
        "ctp/src/mpu/app",
        "ctp/src/mpu/lib",
        "ag35",
        "asr",
        "k3_asr",
        "mcu-soc",
    )
    if any(marker in joined or marker in workspace_text for marker in soc_markers):
        return "mcu-soc"
    if "/mpu" in joined or "_mpu" in joined:
        return "mcu-mpu"
    if has_mcu:
        return "mcu-only"
    return "unknown"

def build_fingerprints(workspace: Path, files: list[Path]) -> list[dict[str, str]]:
    try:
        canonical_workspace = workspace.resolve(strict=True)
    except OSError:
        return []
    fingerprints: list[dict[str, str]] = []
    for path in files:
        try:
            path_stat = path.lstat()
            resolved_path = path.resolve(strict=True)
        except OSError:
            continue
        if (
            is_reparse_point(path)
            or not stat_module.S_ISREG(path_stat.st_mode)
            or not is_lexically_relative_to(resolved_path, canonical_workspace)
        ):
            continue
        path = resolved_path
        is_manifest = path.parent.name == "manifests" and path.suffix.lower() == ".xml"
        is_sdk_manifest = path.parent.name == "sdk_ver" and path.name.endswith("_manifest.xml")
        is_key_file = (
            path.suffix.lower() in FINGERPRINT_SUFFIXES
            or path.name in FINGERPRINT_NAMES
            or is_manifest
            or is_sdk_manifest
        )
        if not is_key_file:
            continue
        digest = sha256_file(path)
        if not digest:
            continue
        fingerprints.append({"path": rel(path, workspace), "sha256": digest})
    return fingerprints[:200]

def background_id(project: str, generated_at: str, fingerprints: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for item in fingerprints:
        digest.update(item["path"].encode("utf-8", errors="ignore"))
        digest.update(item["sha256"].encode("ascii", errors="ignore"))
    return f"{safe_project_id(project)}:{generated_at}:{digest.hexdigest()[:12]}"

def discover_background(
    project: str,
    workspace: Path,
    mcu_keil_project: str | None = None,
    selection_source: str | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    generated_at = now_iso()
    files = iter_files(workspace)
    manifests = []
    keil_projects = []
    build_files = []
    repos = []

    for file in files:
        if file.parent.name == "manifests" and file.suffix.lower() == ".xml":
            manifests.append({
                "path": rel(file, workspace),
                "project_count": len(parse_manifest(file)),
            })
        if file.suffix.lower() in {".uvprojx", ".uvproj"}:
            keil_projects.append(parse_keil(file, workspace))
            build_files.append({"kind": "keil", "path": rel(file, workspace)})
        elif file.name in FINGERPRINT_NAMES or file.name.lower().startswith("build"):
            if file.suffix.lower() in {"", ".sh", ".ps1", ".bat", ".cmd", ".py", ".txt"} or file.name == "CMakeLists.txt":
                build_files.append({"kind": "build_file", "path": rel(file, workspace)})

    for child in sorted(workspace.iterdir()) if workspace.exists() else []:
        try:
            child_stat = child.lstat()
            resolved_child = child.resolve(strict=True)
        except OSError:
            continue
        if (
            is_reparse_point(child)
            or not stat_module.S_ISDIR(child_stat.st_mode)
            or not is_lexically_relative_to(resolved_child, workspace)
        ):
            continue
        info = git_info(resolved_child)
        if info:
            info["path"] = rel(resolved_child, workspace)
            repos.append(info)

    fingerprints = build_fingerprints(workspace, files)
    arch = classify_architecture(workspace, manifests)
    chips = sorted({item.get("device", "").split(":", 1)[0] for item in keil_projects if item.get("device")})
    targets = infer_targets(
        workspace,
        arch,
        build_files,
        keil_projects,
        mcu_keil_project=mcu_keil_project,
        selection_source=selection_source,
    )
    capabilities = infer_capabilities(targets, build_files)
    bg_id = background_id(project, generated_at, fingerprints)
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": safe_project_id(project),
        "background_id": bg_id,
        "generated_at": generated_at,
        "workspace": str(workspace),
        "architecture": arch,
        "targets": targets,
        "manifests": manifests,
        "repos": repos,
        "toolchains": {"keil_projects": keil_projects, "chips": chips},
        "build_files": build_files,
        "capabilities": capabilities,
        "fingerprints": fingerprints,
        "refresh_triggers": [
            "manifest hash changed",
            "Keil project hash changed",
            "build wrapper hash changed",
            "workspace path changed",
        ],
    }

def select_keil_project(
    keil_projects: list[dict[str, Any]],
    selected_path: str | None,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    if not keil_projects:
        return None, "missing", []
    candidates = [str(item.get("path")) for item in keil_projects]
    if not selected_path:
        return None, "selection_required", candidates
    normalized = selected_path.replace("\\", "/").removeprefix("./").casefold()
    selected = next(
        (
            item
            for item in keil_projects
            if str(item.get("path", "")).replace("\\", "/").casefold() == normalized
        ),
        None,
    )
    if selected is None:
        return None, "invalid_selection", candidates
    if selected.get("output_kind") == "library":
        return None, "invalid_kind", candidates
    return selected, "selected", candidates

def infer_targets(
    workspace: Path,
    architecture: str,
    build_files: list[dict[str, str]],
    keil_projects: list[dict[str, Any]],
    mcu_keil_project: str | None = None,
    selection_source: str | None = None,
) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    if (workspace / "mcu").exists() or any(item["kind"] == "keil" for item in build_files):
        selected, selection_status, candidates = select_keil_project(keil_projects, mcu_keil_project)
        targets["mcu"] = {
            "path": str(workspace / "mcu") if (workspace / "mcu").exists() else str(workspace),
            "build": {
                "method": "keil" if keil_projects else "unknown",
                "project": selected.get("path") if selected else None,
                "target": selected.get("target") if selected else None,
                "output": selected.get("output") if selected else None,
                "output_directory": selected.get("output_directory") if selected else None,
                "selection_status": selection_status,
                "selection_candidates": candidates,
                "selection_source": selection_source if selected else None,
            },
        }
    if (workspace / "mpu").exists() or architecture in {"mcu-mpu", "mcu-soc"}:
        cmake = next((item["path"] for item in build_files if item["path"].endswith("CMakeLists.txt")), None)
        targets["mpu"] = {
            "path": str(workspace / "mpu") if (workspace / "mpu").exists() else str(workspace),
            "build": {
                "method": "cmake" if cmake else "unknown",
                "project": cmake,
            },
        }
    return targets

def infer_capabilities(targets: dict[str, Any], build_files: list[dict[str, str]]) -> dict[str, Any]:
    mcu_build = targets.get("mcu", {}).get("build", {})
    if "mcu" not in targets:
        build_mcu_status = "missing"
    elif mcu_build.get("method") == "keil" and mcu_build.get("selection_status") != "selected":
        build_mcu_status = mcu_build.get("selection_status", "selection_required")
    else:
        build_mcu_status = "ready"
    return {
        "project_discovery": {"status": "ready"},
        "build_mcu": {"status": build_mcu_status},
        "build_mpu": {"status": "ready" if "mpu" in targets else "missing"},
        "flash": {"status": "gated", "requires_human_confirm": True},
        "log": {"status": "ready"},
        "hardfault": {"status": "partial", "requires": ["elf", "map", "fault_log"]},
        "build_evidence_count": len(build_files),
    }

def render_background_md(background: dict[str, Any]) -> str:
    caps = background["capabilities"]
    lines = [
        "# Embedded Project Background",
        "",
        f"- Project: `{background['project_id']}`",
        f"- Background: `{background['background_id']}`",
        f"- Workspace: `{background['workspace']}`",
        f"- Architecture: `{background['architecture']}`",
        f"- Generated: `{background['generated_at']}`",
        f"- Chips: {', '.join(background['toolchains'].get('chips') or ['unknown'])}",
        "",
        "## Capabilities",
        "",
        "| Capability | Status |",
        "| --- | --- |",
    ]
    for name, value in caps.items():
        if isinstance(value, dict) and "status" in value:
            lines.append(f"| {name} | {value['status']} |")
    lines.extend([
        "",
        "## Rule",
        "",
        "This background is the Windows Runtime canonical project context. Calling",
        "agents should call the Windows embedded agent and review returned evidence,",
        "not reconstruct build or flash commands directly.",
    ])
    return "\n".join(lines) + "\n"

def write_background(paths: AgentPaths, background: dict[str, Any]) -> tuple[Path, Path]:
    safe_project_id(str(background.get("project_id", "")))
    pdir = project_dir(paths, background["project_id"])
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "logs").mkdir(exist_ok=True)
    (pdir / "artifacts").mkdir(exist_ok=True)
    json_path = pdir / "background.json"
    md_path = pdir / "background.md"
    json_path.write_text(json.dumps(background, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_background_md(background), encoding="utf-8")
    return json_path, md_path

def read_background(paths: AgentPaths, project: str) -> dict[str, Any] | None:
    path = background_path(paths, project)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = safe_project_id(project)
        actual = safe_project_id(str(value.get("project_id", ""))) if isinstance(value, dict) else ""
        if actual != expected:
            return None
        workspace_value = value.get("workspace")
        if not isinstance(workspace_value, str) or not workspace_value.strip():
            return None
        workspace, _ = resolve_managed_workspace(
            workspace_value,
            must_exist=True,
            workspace_root=paths.workspace_root,
        )
        if workspace is None:
            return None
        # Downstream consumers receive only the canonical path that was just
        # checked, never the serialized path that may have been rebound.
        validated = dict(value)
        validated["workspace"] = str(workspace)
        return validated
    except (OSError, json.JSONDecodeError, ValueError):
        return None

def append_run(paths: AgentPaths, project: str, item: dict[str, Any]) -> None:
    pdir = project_dir(paths, project)
    pdir.mkdir(parents=True, exist_ok=True)
    with runs_path(paths, project).open("a", encoding="utf-8") as handle:
        handle.write(json_dump(item) + "\n")

def read_runs(paths: AgentPaths, project: str) -> list[dict[str, Any]]:
    path = runs_path(paths, project)
    runs: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return runs
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            runs.append(value)
    return runs

def latest_run(runs: list[dict[str, Any]], operation: str, ok: bool | None = None) -> dict[str, Any] | None:
    for item in reversed(runs):
        if item.get("operation") != operation:
            continue
        if ok is not None and bool(item.get("ok")) != ok:
            continue
        return item
    return None

def backend_of(run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {}
    backend = run.get("backend")
    return backend if isinstance(backend, dict) else {}

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")

def run_agentctl(args: argparse.Namespace, agentctl_args: list[str]) -> dict[str, Any]:
    agentctl, trust_failure = trusted_agentctl()
    if agentctl is None:
        return result(
            False,
            "agentctl",
            126,
            capability_available=False,
            first_failure=trust_failure,
        )
    command = [sys.executable, str(agentctl), *agentctl_args, "--json"]
    environment = os.environ.copy()
    environment.pop("EMBEDDED_AGENTCTL", None)
    environment.pop("EMBEDDED_SDK_MANAGER", None)
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=environment,
        )
    except OSError as exc:
        return result(
            False,
            "agentctl",
            127,
            first_failure=str(exc),
            command=command,
        )
    stdout_text, _, stdout_binary = decode_text(completed.stdout or b"")
    stderr_text, _, stderr_binary = decode_text(completed.stderr or b"")
    if stdout_binary or stdout_text is None:
        stdout_text = (completed.stdout or b"").decode("utf-8", errors="replace")
    if stderr_binary or stderr_text is None:
        stderr_text = (completed.stderr or b"").decode("utf-8", errors="replace")
    stdout = stdout_text.strip()
    stderr = stderr_text.strip()
    parsed: dict[str, Any] | None = None
    if stdout:
        try:
            parsed = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            parsed = None
    if parsed is None:
        parsed = result(
            completed.returncode == 0,
            "agentctl",
            completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    parsed["backend_command"] = command
    return parsed
