"""Shared helpers for controlled Windows Python backends."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BIN_DIR = Path(__file__).resolve().parent
AGENT_HOME = Path(os.environ.get("EMBEDDED_AGENT_HOME", str(BIN_DIR.parent))).resolve()
LOG_DIR = AGENT_HOME / "logs"
RUNTIME_DIR = BIN_DIR.parent / "embedded-agent"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_contract import capability_result, contract_now_iso  # noqa: E402
from embedded_runtime_common import (  # noqa: E402
    ensure_workspace_output_directory,
    is_reparse_point,
    iter_tool_files,
    validated_workspace_output_path,
)


JLINK_DEVICE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}\Z")
JLINK_INTERFACES = {"SWD", "JTAG", "CJTAG", "FINE"}


def now_iso() -> str:
    return contract_now_iso()


def new_log_path(operation: str, suffix: str = ".log") -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return LOG_DIR / f"{operation}-{stamp}{suffix}"


def file_info(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    item = Path(path)
    try:
        item_stat = item.lstat()
        resolved = item.resolve(strict=True)
    except OSError:
        return None
    if is_reparse_point(item) or not stat.S_ISREG(item_stat.st_mode):
        return None
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return {
        "path": str(resolved),
        "size": item_stat.st_size,
        "mtime": datetime.fromtimestamp(item_stat.st_mtime, timezone.utc).isoformat(),
        "sha256": digest.hexdigest(),
    }


def latest_artifact(roots: Iterable[Path | str], patterns: Iterable[str]) -> dict[str, Any] | None:
    candidates: list[Path] = []
    normalized_patterns = tuple(pattern.lower() for pattern in patterns)
    for root_value in roots:
        root = Path(root_value)
        candidates.extend(
            item
            for item in iter_tool_files(root)
            if any(fnmatch.fnmatchcase(item.name.lower(), pattern) for pattern in normalized_patterns)
        )
    if not candidates:
        return None
    return file_info(max(candidates, key=lambda item: item.stat().st_mtime))


def first_match(path: Path, patterns: Iterable[str]) -> str | None:
    if not path.is_file():
        return None
    expressions = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            if any(expression.search(text) for expression in expressions):
                return text
    return None


def result(ok: bool, operation: str, exit_code: int = 0, **fields: Any) -> dict[str, Any]:
    return capability_result(ok, operation, exit_code, timestamp=now_iso(), **fields)


def failure(operation: str, exit_code: int, message: str, **fields: Any) -> dict[str, Any]:
    return result(False, operation, exit_code, first_failure=message, **fields)


def emit(value: dict[str, Any], as_json: bool) -> int:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":") if as_json else None, indent=None if as_json else 2))
    return int(value.get("exit_code", 0 if value.get("ok") else 1))


def write_log(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content
    path.write_text(text, encoding="utf-8")


def strict_single_line(value: str | Path, label: str, maximum: int = 1024) -> str:
    text = str(value)
    if not text or len(text) > maximum or len(text.splitlines()) != 1:
        raise ValueError(f"{label} must be a non-empty single-line value")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        raise ValueError(f"{label} contains a control character")
    return text


def jlink_device_token(value: str) -> str:
    token = strict_single_line(value, "JLink device", 128)
    if not JLINK_DEVICE_PATTERN.fullmatch(token):
        raise ValueError("JLink device contains unsupported characters")
    return token


def jlink_interface_token(value: str) -> str:
    token = strict_single_line(value, "JLink interface", 16).upper()
    if token not in JLINK_INTERFACES:
        raise ValueError(f"JLink interface must be one of: {', '.join(sorted(JLINK_INTERFACES))}")
    return token


def jlink_speed_token(value: str | int) -> str:
    token = strict_single_line(str(value), "JLink speed", 8)
    if not re.fullmatch(r"[0-9]{1,6}", token):
        raise ValueError("JLink speed must be a decimal integer")
    speed = int(token)
    if not 1 <= speed <= 50000:
        raise ValueError("JLink speed must be between 1 and 50000 kHz")
    return str(speed)


def jlink_address_token(value: str, label: str = "JLink address") -> str:
    token = strict_single_line(value, label, 18)
    if not re.fullmatch(r"0[xX][0-9A-Fa-f]{1,8}", token):
        raise ValueError(f"{label} must be a 32-bit hexadecimal address")
    return f"0x{int(token, 16):08X}"


def jlink_size_token(value: int, label: str = "JLink size", maximum: int = 0xFFFFFFFF) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be an integer between 1 and {maximum}")
    return str(value)


def jlink_script_path(path: Path | str, label: str) -> str:
    raw = strict_single_line(path, label, 1024)
    if '"' in raw:
        raise ValueError(f'{label} cannot contain a double quote')
    try:
        resolved = Path(raw).resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"{label} is invalid: {exc}") from exc
    normalized = strict_single_line(resolved, label, 1024)
    if '"' in normalized:
        raise ValueError(f'{label} cannot contain a double quote')
    return f'"{normalized}"'


def run_logged(
    command: list[str],
    log: Path,
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    error_log: Path | None = None,
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        write_log(log, stdout)
        if error_log:
            write_log(error_log, stderr)
        return 124, stdout, stderr
    except OSError as exc:
        write_log(log, str(exc))
        return 127, "", str(exc)
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    write_log(log, stdout)
    if error_log:
        write_log(error_log, stderr)
    elif stderr:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(stderr)
    return completed.returncode, stdout, stderr


def parse_json_flag(arguments: list[str]) -> tuple[list[str], bool]:
    as_json = "-Json" in arguments or "--json" in arguments
    return [item for item in arguments if item not in {"-Json", "--json"}], as_json


def python_adapter(script_name: str, arguments: list[str]) -> list[str]:
    return [sys.executable, str(BIN_DIR / script_name), *arguments]
