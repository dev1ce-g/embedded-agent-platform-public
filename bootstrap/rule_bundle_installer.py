#!/usr/bin/env python3
"""Install the platform-owned embedded rule bundle into a project projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


BUNDLE_ID = "embedded-engineering-v1"
SCHEMA_VERSION = "embedded-rule-bundle-installer/v1"
LOCK_SCHEMA_VERSION = "embedded-rule-bundle-lock/v1"
RULE_SOURCE = Path("rules/embedded-engineering-v1")
RULE_DESTINATION = Path(".embedded-agent/rules/platform")
LOCK_NAME = ".bundle-lock.json"
CANDIDATE_SUFFIX = ".platform.new"


@dataclass
class InstallResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def candidate_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{CANDIDATE_SUFFIX}")


def validate_output_path(root: Path, path: Path) -> None:
    """Reject destinations outside root or below any symlink component."""
    safe_root = root.resolve()
    absolute = Path(os.path.abspath(path))
    try:
        relative_path = absolute.relative_to(safe_root)
    except ValueError as error:
        raise ValueError(f"rule destination escapes project root: {path}") from error
    current = safe_root
    for index, part in enumerate(relative_path.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"refusing to write through symlink: {current}")
        if current.exists():
            is_final = index == len(relative_path.parts) - 1
            if is_final and not current.is_file():
                raise ValueError(f"rule destination is not a regular file: {current}")
            if not is_final and not current.is_dir():
                raise ValueError(f"rule destination parent is not a directory: {current}")


def atomic_write_bytes(
    path: Path,
    content: bytes,
    dry_run: bool,
    *,
    root: Path | None = None,
) -> None:
    if dry_run:
        return
    if root is not None:
        validate_output_path(root, path)
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


def read_lock(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid rule bundle lock: {path}: {error}") from error
    if value.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise ValueError(f"unsupported rule bundle lock schema: {path}")
    if not isinstance(value.get("managed_files", {}), dict):
        raise ValueError(f"invalid managed_files in rule bundle lock: {path}")
    return value


def bundle_sources(template_root: Path) -> dict[str, bytes]:
    if not template_root.is_dir():
        raise ValueError(f"rule bundle not found: {template_root}")
    files: dict[str, bytes] = {}
    for source in sorted(template_root.rglob("*")):
        if not source.is_file() or source.name == ".DS_Store":
            continue
        if source.is_symlink():
            raise ValueError(f"rule bundle source must not be a symlink: {source}")
        files[relative(source, template_root)] = source.read_bytes()
    if "index.md" not in files:
        raise ValueError(f"rule bundle has no index.md: {template_root}")
    return files


def validate_destination(root: Path) -> None:
    current = root
    while current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError(f"refusing to write through symlink: {current}")
        current = current.parent


def install_rules(
    template_root: Path,
    target_root: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> tuple[InstallResult, dict[str, Any]]:
    destination_root = target_root / RULE_DESTINATION
    validate_destination(destination_root)
    lock_path = destination_root / LOCK_NAME
    validate_output_path(target_root, lock_path)
    previous = read_lock(lock_path)
    previous_managed = {
        str(path): str(digest)
        for path, digest in previous.get("managed_files", {}).items()
    }
    sources = bundle_sources(template_root)
    desired = {path: sha256_bytes(content) for path, content in sources.items()}
    managed = dict(previous_managed)
    result = InstallResult()
    actions: list[tuple[Path, bytes]] = []

    # Preflight the complete bundle before making the first write.
    for rule_path, content in sources.items():
        destination = destination_root / rule_path
        validate_output_path(target_root, destination)
        destination_rel = relative(destination, target_root)
        desired_hash = desired[rule_path]
        if not destination.exists():
            actions.append((destination, content))
            managed[rule_path] = desired_hash
            result.created.append(destination_rel)
            continue
        if not destination.is_file() or destination.is_symlink():
            raise ValueError(f"rule destination is not a regular file: {destination}")
        current_hash = sha256_file(destination)
        if current_hash == desired_hash:
            managed[rule_path] = desired_hash
            result.skipped.append(destination_rel)
            continue
        safe_platform_update = previous_managed.get(rule_path) == current_hash
        if overwrite or safe_platform_update:
            actions.append((destination, content))
            managed[rule_path] = desired_hash
            result.updated.append(destination_rel)
            continue

        candidate = candidate_path(destination)
        validate_output_path(target_root, candidate)
        if candidate.exists():
            if not candidate.is_file() or candidate.is_symlink():
                raise ValueError(f"rule candidate is not a regular file: {candidate}")
            if candidate.read_bytes() != content:
                raise ValueError(
                    f"rule candidate already contains different content: {candidate}"
                )
        else:
            actions.append((candidate, content))
        result.candidates.append(relative(candidate, target_root))

    for rule_path in sorted(set(previous_managed) - set(sources)):
        destination = destination_root / rule_path
        if destination.exists():
            result.orphans.append(relative(destination, target_root))

    lock: dict[str, Any] = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "bundle_id": BUNDLE_ID,
        "bundle_sha256": sha256_bytes(canonical_json(desired)),
        "managed_files": dict(sorted(managed.items())),
        "desired_files": dict(sorted(desired.items())),
        "conflicts": sorted(result.candidates),
        "orphans": sorted(result.orphans),
    }
    lock_bytes = json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if not lock_path.exists() or lock_path.read_bytes() != lock_bytes:
        actions.append((lock_path, lock_bytes))

    for path, content in actions:
        atomic_write_bytes(path, content, dry_run, root=target_root)
    return result, lock


def build_report(
    target: Path,
    result: InstallResult,
    lock: dict[str, Any],
    overwrite: bool,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "rule-bundle-install",
        "ok": True,
        "target": str(target),
        "bundle_id": BUNDLE_ID,
        "bundle_sha256": lock["bundle_sha256"],
        "overwrite": overwrite,
        "dry_run": dry_run,
        "result": asdict(result),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    target = args.target.resolve()
    template_root = source_root() / RULE_SOURCE
    if not target.is_dir():
        print(f"error: target directory not found: {target}", file=sys.stderr)
        return 2
    try:
        result, lock = install_rules(
            template_root=template_root,
            target_root=target,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    report = build_report(target, result, lock, args.overwrite, args.dry_run)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"embedded rule bundle: {target}")
        for key, values in asdict(result).items():
            print(f"{key}: {len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
