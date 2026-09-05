#!/usr/bin/env python3
"""Install the Windows Runtime into a user-selected local directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent
PLATFORM_VERSION_SOURCE = SOURCE_ROOT.parents[1] / "VERSION"
MANAGED_DIRECTORIES = ("bin", "embedded-agent", "can-runtime")
OBSOLETE_MANAGED_FILES = ("bin/claude-start.py",)


def default_prefix() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) / "EmbeddedAgentPlatform" if local_app_data else Path.home() / ".embedded-agent-platform"


def copy_runtime(prefix: Path) -> list[str]:
    written: list[str] = []
    for name in MANAGED_DIRECTORIES:
        source = SOURCE_ROOT / name
        destination = prefix / name
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "site-packages-*", "tests"),
        )
        written.append(str(destination))

    # copytree updates managed directories in place. Remove exact files retired
    # by newer releases so upgrades cannot leave an old model-specific entry
    # point executable on the host.
    for relative in OBSOLETE_MANAGED_FILES:
        obsolete = prefix / relative
        if obsolete.is_file() or obsolete.is_symlink():
            obsolete.unlink()

    launcher = prefix / "embedded-agent.cmd"
    launcher.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        f'"{sys.executable}" "%~dp0bin\\embedded-agent.py" %*\r\n',
        encoding="utf-8",
    )
    written.append(str(launcher))

    config = prefix / "config.example.ps1"
    shutil.copy2(SOURCE_ROOT / "config.example.ps1", config)
    written.append(str(config))
    connections_example = prefix / "jenkins-connections.example.json"
    shutil.copy2(SOURCE_ROOT / "jenkins-connections.example.json", connections_example)
    written.append(str(connections_example))
    aboot_connections_example = prefix / "aboot-connections.example.json"
    shutil.copy2(SOURCE_ROOT / "aboot-connections.example.json", aboot_connections_example)
    written.append(str(aboot_connections_example))
    version_file = prefix / "VERSION"
    shutil.copy2(PLATFORM_VERSION_SOURCE, version_file)
    written.append(str(version_file))
    (prefix / "state").mkdir(parents=True, exist_ok=True)
    return written


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=default_prefix())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    prefix = args.prefix.expanduser().resolve()
    if prefix == SOURCE_ROOT or prefix in SOURCE_ROOT.parents or SOURCE_ROOT in prefix.parents:
        parser.error("--prefix must be outside the source runtime directory")
    prefix.mkdir(parents=True, exist_ok=True)
    written = copy_runtime(prefix)
    result = {
        "ok": True,
        "operation": "windows-runtime-install",
        "prefix": str(prefix),
        "launcher": str(prefix / "embedded-agent.cmd"),
        "config_example": str(prefix / "config.example.ps1"),
        "jenkins_connections_example": str(prefix / "jenkins-connections.example.json"),
        "aboot_connections_example": str(prefix / "aboot-connections.example.json"),
        "written": written,
    }
    print(json.dumps(result, ensure_ascii=args.json, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
