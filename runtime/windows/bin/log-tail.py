#!/usr/bin/env python3
from __future__ import annotations

import argparse

from agent_backend_common import *


PATTERNS = {
    "build": ("build-*.log", "*build*.log"),
    "serial": ("serial-*.log", "*serial*.log"),
    "flash": ("flash-*.log", "*flash*.log"),
    "rtt": ("rtt-*.log", "*rtt*.log"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Kind", choices=PATTERNS, default="build")
    parser.add_argument("-Since", default="10m")
    parser.add_argument("-Lines", type=int, default=120)
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    candidates: set[Path] = set()
    for pattern in PATTERNS[args.Kind]:
        candidates.update(item for item in LOG_DIR.glob(pattern) if item.is_file())
    if not candidates:
        return emit(failure("log-tail", 1, f"No {args.Kind} log found", kind=args.Kind, since=args.Since), args.Json)
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    lines = latest.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-max(1, args.Lines) :]
    return emit(
        result(True, "log-tail", kind=args.Kind, since=args.Since, log=str(latest), mtime=datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc).isoformat(), lines=lines),
        args.Json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
