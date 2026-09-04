#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re

from adb_backend_common import *
from agent_backend_common import *


CONFIG = "/vendor/app/hq/etc/hubs_app.ini"
CACHE = "/vendor/data/gnss_agps/agnss_live.ubx"
META = f"{CACHE}.meta"
WGET_LOG = "/media/card/log/gnss/agps_wget_update.log"
DEBUG_LOG = "/media/card/log/gnss/agps_debug.log"
PATTERNS = (r"read local AGPS", r"AGPS MGA", r"inject len=", r"ACK result", r"accepted=", r"rejected=", r"timeout", r"failed", r"download", r"cache", r"agps")


def shell(adb: str, serial: str, command: str, log: Path, title: str, sanitize: bool = False) -> list[str]:
    _, lines = adb_shell(adb, serial, command)
    output = safe_lines(lines) if sanitize else lines
    append_section(log, title, output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Serial", default="")
    parser.add_argument("-Lines", type=int, default=120)
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "adb-smoke"
    started = now_iso()
    log = new_log_path(operation)
    adb = resolve_adb()
    if not adb:
        return emit(failure(operation, 127, "adb not found in Windows PATH or known platform-tools locations", log=str(log)), args.Json)
    code, devices = adb_raw(adb, None, ["devices"])
    append_section(log, "adb devices", devices)
    available = online_devices(devices)
    serial = args.Serial or (available[0] if available else "")
    if code != 0 or not serial:
        return emit(failure(operation, 1, "No online adb device found", log=str(log), devices=devices), args.Json)
    lines = max(20, min(500, args.Lines))
    uname = shell(adb, serial, "uname -a 2>/dev/null || true", log, "uname")
    uptime = shell(adb, serial, "cat /proc/uptime 2>/dev/null || uptime 2>/dev/null || true", log, "uptime")
    processes = shell(adb, serial, "ps 2>/dev/null || true", log, "processes")
    config_all = shell(adb, serial, f"if [ -f {CONFIG} ]; then cat {CONFIG}; else echo MISSING; fi", log, "hubs_app.ini", True)
    config = [line for line in config_all if re.match(r"^\s*(plug_path|agps_enable|agps_url|agps_refresh_interval_ms)\s*=", line)]
    cache_ls = shell(adb, serial, f"if [ -e {CACHE} ]; then ls -l {CACHE}; else echo MISSING; fi", log, "agps cache")
    meta = shell(adb, serial, f"if [ -f {META} ]; then cat {META}; else echo MISSING; fi", log, "agps metadata", True)
    wget = shell(adb, serial, f"if [ -f {WGET_LOG} ]; then tail -n {lines} {WGET_LOG}; else echo MISSING; fi", log, "agps wget", True)
    debug = shell(adb, serial, f"if [ -f {DEBUG_LOG} ]; then tail -n {lines} {DEBUG_LOG}; else echo MISSING; fi", log, "agps debug", True)
    process_summary = {name: sum(name in line for line in processes) for name in ("hqinit", "hubs_app", "agps_wget_update", "file_download_app", "file_upload_app")}
    size = None
    for line in cache_ls:
        match = re.match(r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+", line)
        if match:
            size = int(match.group(1))
            break
    return emit(result(True, operation, started_at=started, ended_at=now_iso(), log=str(log), adb=adb, device=serial, devices=devices, system={"uname": uname, "uptime": uptime}, processes=process_summary, process_lines=processes, config=key_values(config), config_lines=config, cache={"path": CACHE, "exists": size is not None, "size": size, "ls": cache_ls}, meta_lines=meta, agps_wget_highlights=highlights(wget, PATTERNS, 60), agps_debug_highlights=highlights(debug, PATTERNS, 80)), args.Json)


if __name__ == "__main__":
    raise SystemExit(main())
