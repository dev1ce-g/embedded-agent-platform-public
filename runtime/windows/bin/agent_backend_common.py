"""Shared helpers for controlled Windows Python backends."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BIN_DIR = Path(__file__).resolve().parent
AGENT_HOME = Path(os.environ.get("EMBEDDED_AGENT_HOME", str(BIN_DIR.parent))).resolve()
LOG_DIR = AGENT_HOME / "logs"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_log_path(operation: str, suffix: str = ".log") -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return LOG_DIR / f"{operation}-{stamp}{suffix}"


def file_info(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    item = Path(path)
    if not item.is_file():
        return None
    stat = item.stat()
    digest = hashlib.sha256()
    with item.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(item.resolve()),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": digest.hexdigest(),
    }


def latest_artifact(roots: Iterable[Path | str], patterns: Iterable[str]) -> dict[str, Any] | None:
    candidates: list[Path] = []
    for root_value in roots:
        root = Path(root_value)
        if not root.is_dir():
            continue
        for pattern in patterns:
            candidates.extend(item for item in root.rglob(pattern) if item.is_file())
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
    value: dict[str, Any] = {"ok": ok, "operation": operation, "exit_code": exit_code}
    value.update(fields)
    return value


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
