#!/usr/bin/env python3
"""Discover embedded project facts and build model-independent profiles.

The scanner is intentionally parser-first and read-only. It never builds,
flashes, debugs, or tails logs; it only records evidence for future agents.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "embedded-project-discovery/v1"
IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".DS_Store",
    ".cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "out",
    ".embedded-agent",
    ".trellis",
}
KNOWN_LAYERS = (
    "business",
    "framework",
    "rte_component",
    "project",
    "sdk",
    "third_party",
)
BUILD_NAMES = {
    "CMakeLists.txt",
    "Makefile",
    "makefile",
    "build.sh",
    "build.ps1",
    "build-mcu.ps1",
    "build-mpu.ps1",
    "package.sh",
    "package.ps1",
}
BUILD_SUFFIXES = (".uvprojx", ".uvproj", ".sln", ".mk", ".ninja")
FLASH_KEYWORDS = ("flash", "jlink", "burn", "program")
LOG_KEYWORDS = ("log-tail", "serial", "uart", "adb", "can")
HARDFAULT_KEYWORDS = ("hardfault", "fault", "addr2line", "callstack", "map")
POWER_KEYWORDS = ("pmu", "power", "low_power", "sleep", "wake")
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


@dataclass
class ScanState:
    root: Path
    generated_at: str
    evidence: list[dict[str, str]] = field(default_factory=list)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to <root>/.embedded-agent/context after root resolution.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-summary", action="store_true")
    return parser.parse_args(argv)


def resolve_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".embedded-agent").is_dir():
            return candidate
    return current


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_symlink_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def is_contained_entry(path: Path, root: Path, *, directory: bool) -> bool:
    if is_symlink_or_reparse(path):
        return False
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)


def walk_files(root: Path) -> list[Path]:
    safe_root = root.resolve(strict=True)
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(safe_root):
        base = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS
            and not d.startswith(".backup-")
            and is_contained_entry(base / d, safe_root, directory=True)
        ]
        for name in filenames:
            path = base / name
            if is_contained_entry(path, safe_root, directory=False):
                files.append(path)
    return sorted(files, key=lambda p: p.as_posix())


def add_evidence(
    state: ScanState,
    kind: str,
    path: Path,
    summary: str,
    confidence: str = "high",
) -> dict[str, str]:
    item = {
        "kind": kind,
        "path": rel(path, state.root),
        "summary": summary,
        "confidence": confidence,
    }
    state.evidence.append(item)
    return item


def run_git(repo: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def discover_git_repos(state: ScanState) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    for dirpath, dirnames, _ in os.walk(state.root):
        base = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS - {".git"}
            and not d.startswith(".backup-")
            and is_contained_entry(base / d, state.root, directory=True)
        ]
        if ".git" in dirnames:
            branch = run_git(base, ["rev-parse", "--abbrev-ref", "HEAD"])
            commit = run_git(base, ["rev-parse", "--short", "HEAD"])
            status = run_git(base, ["status", "--short"])
            repos.append({
                "path": rel(base, state.root),
                "branch": branch,
                "commit": commit,
                "dirty": bool(status),
            })
            add_evidence(state, "git_repo", base / ".git", "nested Git repository")
            dirnames[:] = [d for d in dirnames if d != ".git"]
        dirnames[:] = [d for d in dirnames if d != ".git"]
    return sorted(repos, key=lambda item: item["path"])


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


def discover_manifests(state: ScanState, files: list[Path]) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for path in files:
        if path.parent.name != "manifests" or path.suffix.lower() != ".xml":
            continue
        projects = parse_manifest(path)
        manifests.append({
            "path": rel(path, state.root),
            "project_count": len(projects),
            "projects": projects,
        })
        add_evidence(
            state,
            "manifest",
            path,
            f"repo manifest with {len(projects)} project entries",
        )
    return manifests


def classify_architecture(root: Path, manifests: list[dict[str, Any]]) -> str:
    has_mcu = is_contained_entry(root / "mcu", root, directory=True)
    has_mpu = is_contained_entry(root / "mpu", root, directory=True)
    joined = json.dumps(manifests, ensure_ascii=False).lower()
    if has_mcu and has_mpu:
        return "mcu-mpu"
    if "new_energy/top" in joined or "ctp/src/mpu/" in joined or "home/platform" in joined:
        return "mcu-soc"
    if "/mpu" in joined or "_mpu" in joined:
        return "mcu-mpu"
    if has_mcu:
        return "mcu-only"
    return "unknown"


def discover_packages(state: ScanState) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for child in sorted(state.root.iterdir()):
        if child.name.startswith(".") or not is_contained_entry(child, state.root, directory=True):
            continue
        layer_dirs = [
            name for name in KNOWN_LAYERS
            if is_contained_entry(child / name, state.root, directory=True)
        ]
        git_marker = child / ".git"
        has_git = (
            is_contained_entry(git_marker, state.root, directory=True)
            or is_contained_entry(git_marker, state.root, directory=False)
        )
        if has_git or layer_dirs or child.name in {"mcu", "mpu"}:
            packages.append({
                "name": child.name,
                "path": rel(child, state.root),
                "layers": layer_dirs,
                "git": has_git,
            })
            add_evidence(
                state,
                "package",
                child,
                f"package candidate with layers: {', '.join(layer_dirs) or 'none'}",
                "high" if layer_dirs else "medium",
            )
    return packages


def discover_modules(state: ScanState, packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for package in packages:
        pkg_path = state.root / package["path"]
        for layer in package["layers"]:
            layer_path = pkg_path / layer
            children = [
                p.name for p in sorted(layer_path.iterdir())
                if not p.name.startswith(".")
                and is_contained_entry(p, state.root, directory=True)
            ][:40]
            modules.append({
                "package": package["name"],
                "layer": layer,
                "path": rel(layer_path, state.root),
                "children": children,
                "child_count": len(children),
            })
    return modules


def parse_keil(path: Path, root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": rel(path, root)}
    try:
        xml_root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return result
    for tag, key in (
        ("Device", "device"),
        ("TargetName", "target"),
        ("OutputName", "output"),
        ("OutputDirectory", "output_directory"),
        ("Cpu", "cpu"),
    ):
        elem = xml_root.find(f".//{tag}")
        if elem is not None and elem.text:
            result[key] = elem.text.strip()
    create_executable = xml_root.find(".//CreateExecutable")
    create_library = xml_root.find(".//CreateLib")
    if create_executable is not None and create_executable.text in {"0", "1"}:
        result["create_executable"] = create_executable.text == "1"
    if create_library is not None and create_library.text in {"0", "1"}:
        result["create_library"] = create_library.text == "1"
    if result.get("create_executable") is True and result.get("create_library") is not True:
        result["output_kind"] = "executable"
    elif result.get("create_library") is True and result.get("create_executable") is not True:
        result["output_kind"] = "library"
    else:
        result["output_kind"] = "unknown"
    user_options = path.with_suffix(".uvoptx")
    if is_contained_entry(user_options, root, directory=False):
        try:
            options_root = ET.parse(user_options).getroot()
            monitor = options_root.find(".//pMon")
            result["user_options"] = {
                "path": rel(user_options, root),
                "monitor": monitor.text.strip() if monitor is not None and monitor.text else None,
                "parse_status": "ok",
            }
        except (ET.ParseError, OSError):
            result["user_options"] = {"path": rel(user_options, root), "parse_status": "invalid"}
    toolchain = xml_root.find(".//Toolchain")
    if toolchain is not None:
        result["toolchain"] = toolchain.get("Name", "")
        result["toolchain_version"] = toolchain.get("Version", "")
    return result


def discover_build(state: ScanState, files: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    build_files: list[dict[str, str]] = []
    keil_projects: list[dict[str, str]] = []
    for path in files:
        name = path.name
        suffix = path.suffix.lower()
        is_build = name in BUILD_NAMES or suffix in BUILD_SUFFIXES
        if name.startswith("build") and suffix in {".py", ".sh", ".ps1", ".bat"}:
            is_build = True
        if not is_build:
            continue
        kind = "keil" if suffix in {".uvprojx", ".uvproj"} else "build_file"
        build_files.append({"path": rel(path, state.root), "kind": kind})
        add_evidence(state, "build", path, f"{kind} signal")
        if kind == "keil":
            keil_projects.append(parse_keil(path, state.root))
    return build_files, keil_projects


def discover_scripts(state: ScanState, files: list[Path]) -> dict[str, list[dict[str, str]]]:
    groups = {"flash": [], "log": [], "debug": [], "power": []}
    script_suffixes = {".ps1", ".sh", ".py", ".bat", ".cmd"}
    for path in files:
        lowered = path.name.lower()
        if path.suffix.lower() not in script_suffixes:
            continue
        targets = []
        if any(word in lowered for word in FLASH_KEYWORDS):
            targets.append("flash")
        if any(word in lowered for word in LOG_KEYWORDS):
            targets.append("log")
        if any(word in lowered for word in HARDFAULT_KEYWORDS):
            targets.append("debug")
        if any(word in lowered for word in POWER_KEYWORDS):
            targets.append("power")
        for target in targets:
            groups[target].append({"path": rel(path, state.root)})
            add_evidence(state, f"{target}_script", path, f"{target} wrapper signal")
    return groups


def capability(
    name: str,
    evidence: list[dict[str, str]],
    note: str,
    status: str | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    if evidence:
        resolved_status = status or "detected"
        resolved_confidence = confidence or "high"
    else:
        resolved_status = "missing"
        resolved_confidence = "low"
    return {
        "name": name,
        "status": resolved_status,
        "confidence": resolved_confidence,
        "evidence": evidence[:12],
        "note": note,
    }


def infer_capabilities(
    state: ScanState,
    build_files: list[dict[str, str]],
    scripts: dict[str, list[dict[str, str]]],
    files: list[Path],
) -> list[dict[str, Any]]:
    evidence_by_kind: dict[str, list[dict[str, str]]] = {
        "build": [e for e in state.evidence if e["kind"] == "build"],
        "flash": [e for e in state.evidence if e["kind"] == "flash_script"],
        "log": [e for e in state.evidence if e["kind"] == "log_script"],
        "debug": [e for e in state.evidence if e["kind"] == "debug_script"],
        "power": [e for e in state.evidence if e["kind"] == "power_script"],
    }
    power_files = [
        p for p in files
        if any(word in rel(p, state.root).lower() for word in POWER_KEYWORDS)
    ][:20]
    for path in power_files:
        add_evidence(state, "power_source", path, "power-management source signal", "medium")
    evidence_by_kind["power"].extend(e for e in state.evidence if e["kind"] == "power_source")

    hardfault_files = [
        p for p in files
        if any(word in rel(p, state.root).lower() for word in HARDFAULT_KEYWORDS)
    ][:20]
    for path in hardfault_files:
        add_evidence(state, "hardfault_source", path, "fault-analysis source signal", "medium")
    hardfault_evidence = evidence_by_kind["debug"] + [
        e for e in state.evidence if e["kind"] == "hardfault_source"
    ]

    build_cap = capability(
        "build",
        evidence_by_kind["build"],
        "Build files or wrappers were found; execution still requires task-level command approval.",
    )
    if build_files and not any(item["path"].endswith((".ps1", ".sh", ".py", ".bat")) for item in build_files):
        build_cap["status"] = "partial"
        build_cap["note"] = "Build project files found, but no stable wrapper was detected."

    hardfault_status = "detected" if evidence_by_kind["debug"] else "partial"
    power_status = "detected" if evidence_by_kind["power"] else "partial"

    return [
        build_cap,
        capability("flash", evidence_by_kind["flash"], "Flash wrappers require explicit human approval."),
        capability("log", evidence_by_kind["log"], "Log collection wrappers are read-only if used as documented."),
        capability(
            "hardfault",
            hardfault_evidence,
            "Crash analysis requires ELF/MAP/log artifacts per task.",
            hardfault_status,
            "high" if hardfault_status == "detected" else "medium",
        ),
        capability(
            "power",
            evidence_by_kind["power"],
            "Power analysis evidence is source-level until runbooks exist.",
            power_status,
            "high" if power_status == "detected" else "medium",
        ),
    ]


def build_profiles(state: ScanState, files: list[Path]) -> dict[str, Any]:
    manifests = discover_manifests(state, files)
    repos = discover_git_repos(state)
    packages = discover_packages(state)
    modules = discover_modules(state, packages)
    build_files, keil_projects = discover_build(state, files)
    scripts = discover_scripts(state, files)
    architecture = classify_architecture(state.root, manifests)
    capabilities = infer_capabilities(state, build_files, scripts, files)
    chips = sorted({
        item.get("device", "").split(":", 1)[0]
        for item in keil_projects
        if item.get("device")
    })

    facts = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": state.generated_at,
        "source_root": str(state.root),
        "architecture": architecture,
        "repos": repos,
        "manifests": manifests,
        "packages": packages,
        "modules": modules,
        "build_files": build_files,
        "keil_projects": keil_projects,
        "scripts": scripts,
        "evidence": state.evidence,
    }
    project_profile = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": state.generated_at,
        "source_root": str(state.root),
        "architecture": architecture,
        "repos": repos,
        "packages": packages,
        "modules": modules,
        "manifests": [
            {"path": item["path"], "project_count": item["project_count"]}
            for item in manifests
        ],
        "build_systems": build_files,
    }
    device_profile = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": state.generated_at,
        "architecture": architecture,
        "chips": chips,
        "keil_projects": keil_projects,
        "device_confidence": "high" if chips else "low",
        "notes": [
            "Chip evidence comes from Keil project files when present.",
            "Manifest/package architecture evidence does not prove board revision.",
        ],
    }
    capability_profile = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": state.generated_at,
        "architecture": architecture,
        "capabilities": capabilities,
        "rules": [
            "Detected capability is not execution approval.",
            "Build/flash/debug still require explicit authority, allowed paths, a fixed command and an evidence contract.",
        ],
    }
    return {
        "facts": facts,
        "project_profile": project_profile,
        "device_profile": device_profile,
        "capability_profile": capability_profile,
    }


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_overview(profiles: dict[str, Any]) -> str:
    project = profiles["project_profile"]
    device = profiles["device_profile"]
    caps = profiles["capability_profile"]["capabilities"]
    cap_rows = [[c["name"], c["status"], c["confidence"]] for c in caps]
    return f"""# Project Overview

Generated by the Embedded Agent Platform project discovery tool.

- Architecture: `{project["architecture"]}`
- Repositories: {len(project["repos"])}
- Packages: {len(project["packages"])}
- Modules: {len(project["modules"])}
- Manifest files: {len(project["manifests"])}
- Chips: {", ".join(device["chips"]) if device["chips"] else "unknown"}

## Capabilities

{table(["Capability", "Status", "Confidence"], cap_rows)}

## Agent Rule

This file is discovery output. Treat it as evidence, not authorization. Any
build, flash, debug or hardware-adjacent action still needs explicit authority
and the gates in `.embedded-agent/rules/platform/agent-governance.md`.
"""


def render_module_map(profiles: dict[str, Any]) -> str:
    rows = []
    for item in profiles["project_profile"]["modules"]:
        children = ", ".join(item["children"][:8])
        if item["child_count"] > 8:
            children += ", ..."
        rows.append([item["package"], item["layer"], item["path"], children])
    body = table(["Package", "Layer", "Path", "Children"], rows) if rows else "No modules detected."
    return f"""# Module Map

{body}
"""


def render_build_guide(profiles: dict[str, Any]) -> str:
    rows = [
        [item["kind"], item["path"]]
        for item in profiles["project_profile"]["build_systems"]
    ]
    body = table(["Kind", "Path"], rows) if rows else "No build files detected."
    return f"""# Build Guide

This generated guide only lists build evidence. It does not execute commands.

{body}

## Use In Tasks

Before running any build, record the exact objective, authority, wrapper
command, exit code, log path and artifact evidence in the current task context.
"""


def render_architecture(profiles: dict[str, Any]) -> str:
    project = profiles["project_profile"]
    repos = table(
        ["Path", "Branch", "Commit", "Dirty"],
        [
            [r["path"], r.get("branch", ""), r.get("commit", ""), str(r.get("dirty", ""))]
            for r in project["repos"]
        ],
    ) if project["repos"] else "No Git repositories detected."
    return f"""# Architecture

- Detected architecture: `{project["architecture"]}`

## Repositories

{repos}
"""


def render_runbooks(profiles: dict[str, Any]) -> str:
    rows = [
        [item["name"], item["status"], item["note"]]
        for item in profiles["capability_profile"]["capabilities"]
    ]
    return f"""# Runbooks

Generated runbook index. Detailed runbooks should be curated as capabilities
move from `partial` to repeatable wrapper-backed operation.

{table(["Area", "Status", "Next Rule"], rows)}
"""


def output_files(context_dir: Path, profiles: dict[str, Any]) -> dict[Path, str]:
    overview = render_overview(profiles)
    module_map = render_module_map(profiles)
    build_guide = render_build_guide(profiles)
    architecture = render_architecture(profiles)
    return {
        context_dir / "discovery-facts.json": json.dumps(profiles["facts"], indent=2, ensure_ascii=False),
        context_dir / "project-profile.json": json.dumps(profiles["project_profile"], indent=2, ensure_ascii=False),
        context_dir / "device-profile.json": json.dumps(profiles["device_profile"], indent=2, ensure_ascii=False),
        context_dir / "capability-profile.json": json.dumps(profiles["capability_profile"], indent=2, ensure_ascii=False),
        context_dir / "overview.md": overview,
        context_dir / "architecture.md": architecture,
        context_dir / "module-map.md": module_map,
        context_dir / "build-guide.md": build_guide,
        context_dir / "runbooks" / "index.md": render_runbooks(profiles),
    }


def without_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_generated_at(item)
            for key, item in value.items()
            if key != "generated_at"
        }
    if isinstance(value, list):
        return [without_generated_at(item) for item in value]
    return value


def retain_generation_time(context_dir: Path, profiles: dict[str, Any]) -> None:
    previous_path = context_dir / "discovery-facts.json"
    if not previous_path.is_file():
        return
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if without_generated_at(previous) != without_generated_at(profiles["facts"]):
        return
    generated_at = previous.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        return
    for profile in profiles.values():
        if isinstance(profile, dict) and "generated_at" in profile:
            profile["generated_at"] = generated_at


def validate_output_path(root: Path, path: Path) -> None:
    safe_root = root.resolve()
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(safe_root)
    except ValueError as error:
        raise ValueError(f"discovery output escapes its allowed root: {path}") from error
    current = safe_root
    for index, part in enumerate(relative.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"refusing to write discovery output through symlink: {current}")
        if current.exists():
            is_final = index == len(relative.parts) - 1
            if is_final and not current.is_file():
                raise ValueError(f"discovery output is not a regular file: {current}")
            if not is_final and not current.is_dir():
                raise ValueError(f"discovery output parent is not a directory: {current}")


def write_outputs(files: dict[Path, str], dry_run: bool, root: Path) -> None:
    # Validate the complete output set before making the first write.
    for path in files:
        validate_output_path(root, path)
    for path, content in files.items():
        if dry_run:
            print(f"would write {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_output_path(root, path)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(content.rstrip() + "\n")
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def summary(profiles: dict[str, Any], outputs: dict[Path, str]) -> dict[str, Any]:
    project = profiles["project_profile"]
    device = profiles["device_profile"]
    caps = profiles["capability_profile"]["capabilities"]
    return {
        "schema_version": SCHEMA_VERSION,
        "architecture": project["architecture"],
        "repos": len(project["repos"]),
        "packages": len(project["packages"]),
        "modules": len(project["modules"]),
        "manifests": len(project["manifests"]),
        "chips": device["chips"],
        "capabilities": {item["name"]: item["status"] for item in caps},
        "outputs": [str(path) for path in outputs],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = resolve_root(args.root)
    requested_context = args.output_dir or root / ".embedded-agent" / "context"
    context_dir = Path(os.path.abspath(requested_context))
    output_root = root if args.output_dir is None else context_dir.parent.resolve()
    try:
        validate_output_path(output_root, context_dir / ".output-check")
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if context_dir.exists() and (not context_dir.is_dir() or context_dir.is_symlink()):
        print(f"error: discovery output is not a regular directory: {context_dir}", file=sys.stderr)
        return 2

    state = ScanState(root=root, generated_at=now_iso())
    files = walk_files(root)
    profiles = build_profiles(state, files)
    try:
        validate_output_path(output_root, context_dir / "discovery-facts.json")
        retain_generation_time(context_dir, profiles)
        outputs = output_files(context_dir, profiles)
        write_outputs(outputs, args.dry_run, output_root)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    data = summary(profiles, outputs)
    if args.json_summary:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(
            "discovered "
            f"{data['repos']} repos, {data['packages']} packages, "
            f"{data['modules']} modules, {data['manifests']} manifests"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
