#!/usr/bin/env python3
"""Install pinned CAN dependencies into the managed Runtime directory."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ARCH = "x86" if sys.maxsize <= 2**32 else "x64"
REQUIREMENTS = ROOT / ("requirements-x86.txt" if ARCH == "x86" else "requirements.txt")
TARGET = ROOT / f"site-packages-{ARCH}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args(argv)
    TARGET.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--target",
        str(TARGET),
        "-r",
        str(REQUIREMENTS),
    ]
    if args.upgrade:
        command.append("--upgrade")
    if args.wheelhouse:
        command.extend(("--no-index", "--find-links", str(args.wheelhouse)))
    core = subprocess.run(command, check=False)
    value = {
        "ok": core.returncode == 0,
        "operation": "can-runtime-install",
        "exit_code": core.returncode,
        "python": sys.executable,
        "requirements": str(REQUIREMENTS),
        "target": str(TARGET),
        "architecture": ARCH,
        "wheelhouse": str(args.wheelhouse) if args.wheelhouse else None,
        "zcanpro_adapter": "direct-vendor-dll",
    }
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return core.returncode


if __name__ == "__main__":
    raise SystemExit(main())
