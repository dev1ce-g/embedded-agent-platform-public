#!/usr/bin/env python3
"""Deprecated compatibility adapter for the former copied embedded preset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from embedded_spec_installer import PRESET_NAME, main as install_spec_main


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--preset", default=PRESET_NAME)
    parser.add_argument(
        "--arch",
        choices=("auto", "mcu-only", "mcu-mpu", "mcu-soc"),
        default="auto",
        help="Compatibility hint only; Discovery owns the actual architecture.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-copy-skills", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.preset != PRESET_NAME:
        print(f"error: unsupported preset: {args.preset}", file=sys.stderr)
        return 2

    print(
        "warning: apply_embedded_preset.py is deprecated; use "
        "trellis-embedded-init or embedded_spec_installer.py",
        file=sys.stderr,
    )
    translated = ["--target", str(args.target)]
    if args.overwrite:
        translated.append("--overwrite")
    if args.dry_run:
        translated.append("--dry-run")
    if args.json:
        translated.append("--json")
    return install_spec_main(translated)


if __name__ == "__main__":
    raise SystemExit(main())
