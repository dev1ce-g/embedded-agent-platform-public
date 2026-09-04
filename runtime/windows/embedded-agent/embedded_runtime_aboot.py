"""Python backend for gated ASR Aboot MPU flashing."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

from embedded_runtime_common import DEFAULT_INSTALL_ROOT, decode_text, is_relative_to, now_iso, result, sha256_file


DEFAULT_ABOOT_ROOT = Path(os.environ.get("EMBEDDED_ABOOT_ROOT", str(DEFAULT_INSTALL_ROOT / "tools" / "aboot")))
DEFAULT_FIRMWARE_ROOT = Path(os.environ.get("EMBEDDED_FIRMWARE_ROOT", str(DEFAULT_INSTALL_ROOT / "firmware")))
ABOOT_SUCCESS_PATTERN = re.compile(r"all finished\.\s*total time:", re.IGNORECASE)
ABOOT_FAILURE_PATTERNS = (
    re.compile(r"\bfailed\b", re.IGNORECASE),
    re.compile(r"\bfailure\b", re.IGNORECASE),
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"cannot\s+", re.IGNORECASE),
)
COM_PORT_PATTERN = re.compile(r"COM[1-9][0-9]{0,3}\Z", re.IGNORECASE)
MAX_ABOOT_RESULT_BYTES = 256 * 1024
MPU_RELEASE_MEMBER_PATTERN = re.compile(r"(?:^|/)package/mpu_build/[^/]+\.zip\Z", re.IGNORECASE)


def aboot_file_info(path: Path) -> dict[str, Any]:
    item = path.stat()
    return {
        "path": str(path),
        "size": item.st_size,
        "mtime": item.st_mtime,
        "sha256": sha256_file(path),
    }


def normalize_windows_exit_code(exit_code: int) -> int:
    return exit_code - 0x1_0000_0000 if exit_code > 0x7FFF_FFFF else exit_code


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    else:
        process.kill()
    process.wait(timeout=30)


def normalize_ports(values: list[str] | None) -> tuple[list[str], str | None]:
    ports: list[str] = []
    for value in values or []:
        for item in value.split(","):
            port = item.strip().upper()
            if not port:
                continue
            if not COM_PORT_PATTERN.fullmatch(port):
                return [], f"Invalid serial port: {item}"
            if port not in ports:
                ports.append(port)
    return ports, None


def resolve_workspace_path(workspace: Path, path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (workspace / path).resolve()


def extract_mpu_release_package(
    workspace: Path,
    source: Path,
    source_info: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(source) as archive:
            candidates = [
                item
                for item in archive.infolist()
                if MPU_RELEASE_MEMBER_PATTERN.search(item.filename)
            ]
            if not candidates:
                return None
            if len(candidates) != 1:
                names = [item.filename for item in candidates]
                return result(
                    False,
                    "flash-mpu-aboot-stage",
                    2,
                    source=source_info,
                    candidates=names,
                    first_failure="Combined package must contain exactly one MPU release ZIP",
                )

            member = candidates[0]
            destination = (
                workspace
                / "_codex_builds"
                / "flash-inputs"
                / source_info["sha256"][:16]
                / Path(member.filename).name
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
            try:
                with archive.open(member) as package_input, temporary.open("wb") as package_output:
                    shutil.copyfileobj(package_input, package_output)
                if not zipfile.is_zipfile(temporary):
                    temporary.unlink(missing_ok=True)
                    return result(
                        False,
                        "flash-mpu-aboot-stage",
                        2,
                        source=source_info,
                        selected_member=member.filename,
                        first_failure="Selected MPU release package is not a valid ZIP archive",
                    )
                os.replace(temporary, destination)
            except (OSError, zipfile.BadZipFile) as exc:
                temporary.unlink(missing_ok=True)
                return result(
                    False,
                    "flash-mpu-aboot-stage",
                    1,
                    source=source_info,
                    selected_member=member.filename,
                    first_failure=f"Cannot extract MPU release package: {exc}",
                )
    except (OSError, zipfile.BadZipFile) as exc:
        return result(
            False,
            "flash-mpu-aboot-stage",
            2,
            source=source_info,
            first_failure=f"Cannot inspect release package: {exc}",
        )

    return result(
        True,
        "flash-mpu-aboot-stage",
        source=source_info,
        staged=True,
        nested_extracted=True,
        selected_member=member.filename,
        package_path=str(destination),
        staged_package=aboot_file_info(destination),
    )


def stage_aboot_package(workspace: Path, source: Path, firmware_root: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    source = resolve_workspace_path(workspace, source)
    firmware_root = resolve_workspace_path(workspace, firmware_root)
    if not source.is_file():
        return result(False, "flash-mpu-aboot-stage", 2, first_failure=f"Release package not found: {source}")
    if source.suffix.lower() != ".zip" or not zipfile.is_zipfile(source):
        return result(False, "flash-mpu-aboot-stage", 2, first_failure="Aboot release package must be a valid ZIP archive")
    source_info = aboot_file_info(source)
    if is_relative_to(source, workspace):
        nested_package = extract_mpu_release_package(workspace, source, source_info)
        if nested_package is not None:
            return nested_package
        return result(
            True,
            "flash-mpu-aboot-stage",
            source=source_info,
            staged=False,
            package_path=str(source),
        )
    if not is_relative_to(source, firmware_root):
        return result(
            False,
            "flash-mpu-aboot-stage",
            5,
            blocked=True,
            source=source_info,
            trusted_root=str(firmware_root),
            first_failure="External Aboot package must be under the configured firmware reference root",
        )

    destination = workspace / "_codex_builds" / "flash-inputs" / source_info["sha256"][:16] / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == source_info["sha256"]:
        nested_package = extract_mpu_release_package(workspace, destination, source_info)
        if nested_package is not None:
            return nested_package
        return result(
            True,
            "flash-mpu-aboot-stage",
            source=source_info,
            staged=True,
            reused=True,
            package_path=str(destination),
            staged_package=aboot_file_info(destination),
        )

    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    try:
        shutil.copy2(source, temporary)
        copied_hash = sha256_file(temporary)
        if copied_hash != source_info["sha256"]:
            temporary.unlink(missing_ok=True)
            return result(False, "flash-mpu-aboot-stage", 1, source=source_info, first_failure="Staged Aboot package SHA-256 mismatch")
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return result(False, "flash-mpu-aboot-stage", 1, source=source_info, first_failure=f"Cannot stage Aboot package: {exc}")
    nested_package = extract_mpu_release_package(workspace, destination, source_info)
    if nested_package is not None:
        return nested_package
    return result(
        True,
        "flash-mpu-aboot-stage",
        source=source_info,
        staged=True,
        reused=False,
        package_path=str(destination),
        staged_package=aboot_file_info(destination),
    )


def prepare_aboot_flash(
    *,
    workspace: Path,
    package: Path,
    aboot_root: Path,
    ports: list[str] | None,
    usb_only: bool,
    auto_enable: bool,
    speed: int,
    reboot: bool,
    at_fallback: bool,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    package = resolve_workspace_path(workspace, package)
    aboot_root = resolve_workspace_path(workspace, aboot_root)
    downloader = aboot_root / "adownload.exe"

    if not workspace.is_dir():
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure=f"Workspace not found: {workspace}")
    if not package.is_file():
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure=f"Release package not found: {package}")
    if package.suffix.lower() != ".zip":
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure="Aboot release package must be a .zip file")
    if not zipfile.is_zipfile(package):
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure="Aboot release package is not a valid ZIP archive")
    if not is_relative_to(package, workspace):
        return result(False, "flash-mpu-aboot-preflight", 5, blocked=True, first_failure="Aboot release package must be inside the registered project workspace")
    if not downloader.is_file():
        return result(False, "flash-mpu-aboot-preflight", 127, first_failure=f"adownload.exe not found: {downloader}")
    if speed < 1200 or speed > 4_000_000:
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure="Aboot speed must be between 1200 and 4000000")

    normalized_ports, port_failure = normalize_ports(ports)
    if port_failure:
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure=port_failure)
    if usb_only and normalized_ports:
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure="Use either --usb-only or --port, not both")
    if not usb_only and not normalized_ports:
        return result(False, "flash-mpu-aboot-preflight", 2, first_failure="MPU flash requires --usb-only or at least one explicit --port")

    command = [str(downloader), "-q"]
    if normalized_ports:
        command.extend(["-p", ",".join(normalized_ports)])
    if usb_only:
        command.append("-u")
    if auto_enable:
        command.append("-a")
    command.extend(["-s", str(speed)])
    if at_fallback:
        command.append("-f")
    if reboot:
        command.append("-r")
    command.append(str(package))

    return result(
        True,
        "flash-mpu-aboot-preflight",
        command=command,
        package=aboot_file_info(package),
        tool=aboot_file_info(downloader),
        connection={
            "ports": normalized_ports,
            "usb_only": usb_only,
            "auto_enable": auto_enable,
            "speed": speed,
            "reboot": reboot,
            "at_fallback": at_fallback,
        },
    )


def first_failure(text: str) -> str | None:
    for line in text.splitlines():
        value = line.strip()
        if value and any(pattern.search(value) for pattern in ABOOT_FAILURE_PATTERNS):
            return value[:500]
    return None


def read_log_tail(path: Path, max_bytes: int = MAX_ABOOT_RESULT_BYTES) -> tuple[str, bool]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
        data = handle.read(max_bytes)
    text, _, binary = decode_text(data)
    if binary or text is None:
        text = data.decode("utf-8", errors="replace")
    return text, size > max_bytes


def run_aboot_flash(
    *,
    workspace: Path,
    package: Path,
    aboot_root: Path,
    firmware_root: Path,
    ports: list[str] | None,
    usb_only: bool,
    auto_enable: bool,
    speed: int,
    reboot: bool,
    at_fallback: bool,
    timeout: int,
    log_dir: Path,
) -> dict[str, Any]:
    staging = stage_aboot_package(workspace, package, firmware_root)
    if not staging.get("ok"):
        return staging
    staged_package = Path(staging["package_path"])
    preflight = prepare_aboot_flash(
        workspace=workspace,
        package=staged_package,
        aboot_root=aboot_root,
        ports=ports,
        usb_only=usb_only,
        auto_enable=auto_enable,
        speed=speed,
        reboot=reboot,
        at_fallback=at_fallback,
    )
    if not preflight.get("ok"):
        return preflight

    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"flash-mpu-aboot-{stamp}.log"
    started_at = now_iso()
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    try:
        with log_path.open("wb") as output:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(
                preflight["command"],
                cwd=str(aboot_root.resolve()),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
            )
            try:
                exit_code = process.wait(timeout=max(1, timeout))
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                return result(
                    False,
                    "flash-mpu-aboot",
                    124,
                    started_at=started_at,
                    ended_at=now_iso(),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    log=str(log_path),
                    preflight=preflight,
                    staging=staging,
                    first_failure=f"Aboot flash timed out after {max(1, timeout)} seconds",
                )
            except KeyboardInterrupt:
                terminate_process_tree(process)
                return result(
                    False,
                    "flash-mpu-aboot",
                    130,
                    started_at=started_at,
                    ended_at=now_iso(),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    log=str(log_path),
                    preflight=preflight,
                    staging=staging,
                    first_failure="Aboot flash was interrupted; downloader process tree was terminated",
                )
    except OSError as exc:
        return result(
            False,
            "flash-mpu-aboot",
            127,
            started_at=started_at,
            ended_at=now_iso(),
            duration_ms=int((time.monotonic() - started) * 1000),
            log=str(log_path),
            preflight=preflight,
            staging=staging,
            first_failure=str(exc),
        )

    try:
        output_tail, truncated = read_log_tail(log_path)
    except OSError as exc:
        return result(
            False,
            "flash-mpu-aboot",
            1,
            started_at=started_at,
            ended_at=now_iso(),
            duration_ms=int((time.monotonic() - started) * 1000),
            log=str(log_path),
            preflight=preflight,
            staging=staging,
            first_failure=f"Cannot read Aboot evidence log: {exc}",
        )
    exit_code = normalize_windows_exit_code(exit_code)
    success_marker = ABOOT_SUCCESS_PATTERN.search(output_tail)
    failure_marker = first_failure(output_tail)
    try:
        package_after = aboot_file_info(staged_package.resolve())
    except OSError:
        package_after = None
    package_changed = package_after is None or package_after["sha256"] != preflight["package"]["sha256"]
    ok = exit_code == 0 and success_marker is not None and not package_changed
    failure = None if ok else failure_marker
    if not ok and failure is None:
        if package_changed:
            failure = "Aboot release package changed while flashing"
        else:
            failure = "Missing Aboot completion marker: all finished. total time:" if exit_code == 0 else f"adownload.exe exited with code {exit_code}"
    return result(
        ok,
        "flash-mpu-aboot",
        0 if ok else exit_code if exit_code != 0 else 1,
        started_at=started_at,
        ended_at=now_iso(),
        duration_ms=int((time.monotonic() - started) * 1000),
        log=str(log_path),
        output_tail=output_tail,
        output_truncated=truncated,
        success_marker=success_marker.group(0) if success_marker else None,
        failure_marker=failure_marker,
        first_failure=failure,
        package=preflight["package"],
        staging=staging,
        package_after=package_after,
        package_changed=package_changed,
        tool=preflight["tool"],
        connection=preflight["connection"],
        backend_command=preflight["command"],
    )
