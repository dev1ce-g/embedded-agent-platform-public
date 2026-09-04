#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shlex
from urllib.parse import urlsplit

from adb_backend_common import *
from agent_backend_common import *


CONFIG = "/vendor/app/hq/etc/hubs_app.ini"
CACHE = "/vendor/data/gnss_agps/agnss_live.ubx"
META = f"{CACHE}.meta"
WGET_LOG = "/media/card/log/gnss/agps_wget_update.log"
DEBUG_LOG = "/media/card/log/gnss/agps_debug.log"
PROBE = "/tmp/agnss_live.ubx.check"
LOG_PATTERNS = (r"read local AGPS", r"AGPS MGA inject summary", r"MGA ACK", r"ACK accepted", r"ACK rejected", r"ACK timeout", r"inject cfg=", r"download success", r"download failed", r"download invalid", r"cache=")


def add_check(checks: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": safe_line(detail)})


def integer(lines: list[str]) -> int | None:
    for line in lines:
        match = re.search(r"(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def summary_value(line: str, name: str) -> int | None:
    match = re.search(rf"\b{re.escape(name)}=(\d+)", line)
    return int(match.group(1)) if match else None


def run_inspection(adb: str, serial: str, command: str, log: Path, title: str, sanitize: bool = False) -> list[str]:
    _, raw = adb_shell(adb, serial, command)
    output = safe_lines(raw) if sanitize else raw
    append_section(log, title, output)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Serial", default="")
    parser.add_argument("-Lines", type=int, default=160)
    parser.add_argument("-DownloadCheck", action="store_true")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "adb-agps-validate"
    started = now_iso()
    log = new_log_path(operation)
    adb = resolve_adb()
    if not adb:
        return emit(failure(operation, 127, "adb not found in Windows PATH or known platform-tools locations", log=str(log)), args.Json)
    device_code, devices = adb_raw(adb, None, ["devices"])
    append_section(log, "adb devices", devices)
    available = online_devices(devices)
    serial = args.Serial or (available[0] if available else "")
    if device_code != 0 or not serial:
        return emit(failure(operation, 1, "No online adb device found", log=str(log), devices=devices), args.Json)
    line_count = max(20, min(500, args.Lines))
    uname = run_inspection(adb, serial, "uname -a 2>/dev/null || true", log, "uname")
    uptime = run_inspection(adb, serial, "cat /proc/uptime 2>/dev/null || uptime 2>/dev/null || true", log, "uptime")
    processes = run_inspection(adb, serial, "ps 2>/dev/null || true", log, "processes")
    config_all = run_inspection(adb, serial, f"if [ -f {CONFIG} ]; then cat {CONFIG}; else echo MISSING; fi", log, "hubs_app.ini", True)
    cache_ls = run_inspection(adb, serial, f"if [ -e {CACHE} ]; then ls -l {CACHE}; else echo MISSING; fi", log, "cache ls")
    cache_size_lines = run_inspection(adb, serial, f"if [ -f {CACHE} ]; then wc -c < {CACHE}; else echo MISSING; fi", log, "cache size")
    cache_header = run_inspection(adb, serial, f"if [ -f {CACHE} ]; then if command -v od >/dev/null 2>&1; then od -An -tx1 -N 8 {CACHE}; else echo NO_OD; fi; else echo MISSING; fi", log, "cache header")
    metadata = run_inspection(adb, serial, f"if [ -f {META} ]; then cat {META}; else echo MISSING; fi", log, "metadata", True)
    wget_log = run_inspection(adb, serial, f"if [ -f {WGET_LOG} ]; then tail -n {line_count} {WGET_LOG}; else echo MISSING; fi", log, "wget log", True)
    debug_log = run_inspection(adb, serial, f"if [ -f {DEBUG_LOG} ]; then tail -n {line_count} {DEBUG_LOG}; else echo MISSING; fi", log, "debug log", True)

    config_lines = [line for line in config_all if re.match(r"^\s*(plug_path|agps_enable|agps_url|agps_refresh_interval_ms)\s*=", line)]
    config = key_values(config_lines)
    process_summary = {name: sum(name in line for line in processes) for name in ("hqinit", "hubs_app", "agps_wget_update", "file_download_app", "file_upload_app")}
    checks: list[dict[str, str]] = []
    add_check(checks, "ADB device", "PASS", f"serial={serial} adb={adb}")
    add_check(checks, "hubs_app.ini", "FAIL" if "MISSING" in config_all else "PASS", f"{CONFIG} missing" if "MISSING" in config_all else "config file present")
    plug_path = config.get("plug_path", "")
    add_check(checks, "GNSS plugin", "PASS" if "ublox" in plug_path else "FAIL", plug_path or "plug_path missing")
    agps_enable = config.get("agps_enable", "")
    add_check(checks, "AGPS enable", "PASS" if agps_enable == "1" else "FAIL", f"agps_enable={agps_enable}")
    agps_url = config.get("agps_url", "")
    scheme = urlsplit(agps_url).scheme.lower() if agps_url else ""
    url_status = "PASS" if scheme == "http" else "FAIL" if scheme in {"", "https"} else "WARN"
    add_check(checks, "AGPS URL", url_status, safe_url(agps_url) if agps_url else "agps_url missing")
    refresh = config.get("agps_refresh_interval_ms", "")
    add_check(checks, "refresh interval", "PASS" if refresh.isdigit() and int(refresh) > 0 else "WARN", f"agps_refresh_interval_ms={refresh}")
    add_check(checks, "hubs_app process", "PASS" if process_summary["hubs_app"] else "FAIL", f"count={process_summary['hubs_app']}")
    add_check(checks, "wget updater process", "PASS" if process_summary["agps_wget_update"] else "WARN", f"count={process_summary['agps_wget_update']}")
    cache_size = integer(cache_size_lines)
    add_check(checks, "AGPS cache file", "PASS" if cache_size and "MISSING" not in cache_ls else "FAIL", f"size={cache_size} path={CACHE}")
    header_text = " ".join(cache_header).lower()
    header_status = "PASS" if re.search(r"\bb5\s+62\b", header_text) else "WARN" if "NO_OD" in cache_header else "FAIL"
    add_check(checks, "UBX header", header_status, header_text.strip() or "header unavailable")
    add_check(checks, "cache metadata", "WARN" if "MISSING" in metadata else "PASS", "metadata missing" if "MISSING" in metadata else "metadata present")
    add_check(checks, "wget log", "WARN" if "MISSING" in wget_log or not any("download success" in line for line in wget_log) else "PASS", "download success found" if any("download success" in line for line in wget_log) else "no recent download success marker")
    summaries = [line for line in debug_log if re.search(r"(?:ublox )?AGPS MGA inject summary", line)]
    latest_summary = summaries[-1] if summaries else ""
    if latest_summary:
        accepted, rejected = summary_value(latest_summary, "accepted"), summary_value(latest_summary, "rejected")
        timeout, failed = summary_value(latest_summary, "timeout"), summary_value(latest_summary, "failed")
        status = "PASS" if accepted and not (rejected or timeout or failed) else "WARN" if accepted else "FAIL"
        add_check(checks, "AGPS injection evidence", status, latest_summary)
    else:
        add_check(checks, "AGPS injection evidence", "WARN", f"no inject summary in last {line_count} lines")

    download_result = None
    if args.DownloadCheck:
        parsed = urlsplit(agps_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            add_check(checks, "download check", "FAIL", "agps_url is not an absolute HTTP URL")
        else:
            quoted_url = shlex.quote(agps_url)
            command = f"rm -f {PROBE}; wget -S -T 20 -t 2 -O {PROBE} {quoted_url}; rc=$?; echo __WGET_RC:$rc; if [ -f {PROBE} ]; then echo __WGET_SIZE:$(wc -c < {PROBE} 2>/dev/null); if command -v od >/dev/null 2>&1; then od -An -tx1 -N 8 {PROBE}; fi; fi; exit 0"
            _, download_lines = adb_shell(adb, serial, command)
            append_section(log, "download check", safe_lines(download_lines))
            rc = next((int(match.group(1)) for line in download_lines if (match := re.search(r"__WGET_RC:(\d+)", line))), None)
            size = next((int(match.group(1)) for line in download_lines if (match := re.search(r"__WGET_SIZE:(\d+)", line))), None)
            download_header = " ".join(line for line in download_lines if not line.startswith("__WGET_"))
            download_result = {"url": safe_url(agps_url), "rc": rc, "size": size, "path": PROBE, "lines": safe_lines(download_lines)}
            status = "PASS" if rc == 0 and size and re.search(r"\bb5\s+62\b", download_header.lower()) else "WARN" if rc == 0 and size else "FAIL"
            add_check(checks, "download check", status, f"rc={rc} size={size} path={PROBE}")

    fail_count = sum(check["status"] == "FAIL" for check in checks)
    warn_count = sum(check["status"] == "WARN" for check in checks)
    return emit(result(fail_count == 0, operation, 1 if fail_count else 0, started_at=started, ended_at=now_iso(), log=str(log), adb=adb, device=serial, devices=devices, lines=line_count, download_check_enabled=args.DownloadCheck, system={"uname": uname, "uptime": uptime}, processes=process_summary, config={"plug_path": plug_path, "agps_enable": agps_enable, "agps_url": safe_url(agps_url), "agps_refresh_interval_ms": refresh}, cache={"path": CACHE, "size": cache_size, "ls": cache_ls, "header": cache_header, "metadata": safe_lines(metadata)}, checks=checks, fail_count=fail_count, warn_count=warn_count, latest_injection_summary=safe_line(latest_summary), agps_wget_highlights=highlights(wget_log, LOG_PATTERNS, 60), agps_debug_highlights=highlights(debug_log, LOG_PATTERNS, 80), download_check=download_result), args.Json)


if __name__ == "__main__":
    raise SystemExit(main())
