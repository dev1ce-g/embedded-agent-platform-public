"""Shared, bounded ADB inspection helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


KNOWN_ADB = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
    Path(r"C:\platform-tools\adb.exe"),
)


def resolve_adb() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    return next((str(path) for path in KNOWN_ADB if path.is_file()), None)


def adb_raw(adb: str, serial: str | None, arguments: list[str]) -> tuple[int, list[str]]:
    command = [adb]
    if serial:
        command.extend(["-s", serial])
    command.extend(arguments)
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return completed.returncode, completed.stdout.decode("utf-8", errors="replace").splitlines()


def adb_shell(adb: str, serial: str, command: str) -> tuple[int, list[str]]:
    return adb_raw(adb, serial, ["shell", command])


def online_devices(lines: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        match = re.match(r"^\s*(\S+)\s+device\s*$", line)
        if match:
            values.append(match.group(1))
    return values


def safe_url(value: str) -> str:
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "<redacted>" if parsed.query else "", ""))
    except ValueError:
        return re.sub(r"\?.*$", "?<redacted>", value)


def safe_line(line: str) -> str:
    return re.sub(r"https?://\S+", lambda match: safe_url(match.group(0)), line)


def safe_lines(lines: list[str]) -> list[str]:
    return [safe_line(line) for line in lines]


def key_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^\s*([^#;=\s]+)\s*=\s*(.*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def highlights(lines: list[str], patterns: tuple[str, ...], limit: int) -> list[str]:
    expressions = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    return [safe_line(line) for line in lines if any(expression.search(line) for expression in expressions)][-limit:]


def append_section(log: Path, title: str, lines: list[str]) -> None:
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"===== {title} =====\n")
        handle.write("\n".join(lines))
        handle.write("\n\n")
