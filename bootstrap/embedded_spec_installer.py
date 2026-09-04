#!/usr/bin/env python3
"""Install the bundled spec-only template when no Git registry is configured."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


PRESET_NAME = "embedded-dual-machine"
SCHEMA_VERSION = "embedded-spec-installer/v1"
SPEC_SOURCE = Path(
    "marketplace/specs/embedded-dual-machine-v1"
)


@dataclass
class InstallResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def candidate_path(path: Path, preset: str) -> Path:
    return path.with_name(f"{path.name}.{preset}.new")


def write_file(source: Path, destination: Path, dry_run: bool) -> None:
    if dry_run:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def install_spec(
    template_root: Path,
    target_root: Path,
    preset: str,
    overwrite: bool,
    dry_run: bool,
) -> InstallResult:
    result = InstallResult()
    destination_root = target_root / ".trellis" / "spec"

    for source in sorted(template_root.rglob("*")):
        if not source.is_file() or source.name == ".DS_Store":
            continue

        destination = destination_root / source.relative_to(template_root)
        destination_rel = relative(destination, target_root)
        source_bytes = source.read_bytes()

        if not destination.exists():
            write_file(source, destination, dry_run)
            result.created.append(destination_rel)
            continue

        if destination.read_bytes() == source_bytes:
            result.skipped.append(destination_rel)
            continue

        if overwrite:
            write_file(source, destination, dry_run)
            result.updated.append(destination_rel)
            continue

        candidate = candidate_path(destination, preset)
        write_file(source, candidate, dry_run)
        result.candidates.append(relative(candidate, target_root))

    return result


def build_report(
    target: Path,
    result: InstallResult,
    overwrite: bool,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "bundled-spec-fallback",
        "target": str(target),
        "template": PRESET_NAME,
        "overwrite": overwrite,
        "dry_run": dry_run,
        "result": asdict(result),
        "excluded": [
            ".trellis/agents",
            ".trellis/knowledge",
            ".trellis/workflow.md",
            "device and build operations",
        ],
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
    template_root = source_root() / SPEC_SOURCE

    if not target.is_dir():
        print(f"error: target directory not found: {target}", file=sys.stderr)
        return 2
    if not (target / ".trellis").is_dir():
        print(
            "error: target is not initialized; use trellis-embedded-init first",
            file=sys.stderr,
        )
        return 2
    if not template_root.is_dir():
        print(f"error: bundled Spec template not found: {template_root}", file=sys.stderr)
        return 2

    result = install_spec(
        template_root=template_root,
        target_root=target,
        preset=PRESET_NAME,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    report = build_report(target, result, args.overwrite, args.dry_run)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"embedded Spec fallback: {target}")
        for key, values in asdict(result).items():
            print(f"{key}: {len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
