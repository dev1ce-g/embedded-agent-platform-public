"""Internal embedded runtime device module."""

from __future__ import annotations

from embedded_runtime_common import *

def adb_executable() -> str | None:
    configured = os.environ.get("EMBEDDED_AGENT_ADB")
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate) if candidate.is_file() else None
    return shutil.which("adb")

def run_adb(adb: str, arguments: list[str], timeout: int = 15) -> dict[str, Any]:
    command = [adb, *arguments]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(1, timeout),
        )
    except subprocess.TimeoutExpired:
        return result(False, "adb", 124, command=command, first_failure="ADB command timed out")
    except OSError as exc:
        return result(False, "adb", 127, command=command, first_failure=str(exc))
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace").replace("\r", "")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace").replace("\r", "")
    return result(
        completed.returncode == 0,
        "adb",
        completed.returncode,
        command=command,
        stdout=stdout.strip(),
        stderr=stderr.strip(),
        first_failure=(stderr.strip() or None) if completed.returncode else None,
    )

def parse_adb_devices(output: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        properties: dict[str, str] = {}
        for field in fields[2:]:
            if ":" in field:
                key, value = field.split(":", 1)
                properties[key] = value
        devices.append(
            {
                "serial": fields[0],
                "state": fields[1],
                "online": fields[1] == "device",
                "properties": properties,
            }
        )
    return devices

def adb_devices(adb: str, timeout: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    backend = run_adb(adb, ["devices", "-l"], timeout)
    return backend, parse_adb_devices(str(backend.get("stdout") or ""))

def select_adb_device(devices: list[dict[str, Any]], requested: str | None) -> tuple[str | None, str | None]:
    online = [str(device["serial"]) for device in devices if device.get("online")]
    if requested:
        if not ADB_DEVICE_SERIAL_PATTERN.fullmatch(requested):
            return None, "Invalid ADB device serial"
        if requested not in online:
            return None, "Requested ADB device is not online"
        return requested, None
    if not online:
        return None, "No online ADB device found"
    if len(online) > 1:
        return None, "Multiple online ADB devices found; pass --serial"
    return online[0], None

def command_device(args: argparse.Namespace) -> int:
    operation = f"device-{args.device_action}"
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        print_result(result(False, operation, 2, project_id=safe_project_id(args.project), first_failure="Project background not found"), args.json)
        return 2

    tty_name: str | None = None
    if args.device_action == "serial-inspect":
        tty_name = args.tty
        if not ADB_TTY_NAME_PATTERN.fullmatch(tty_name):
            value = result(False, operation, 2, project_id=background["project_id"], background_id=background["background_id"], tty=tty_name, first_failure="--tty must be a tty device name such as ttyS2")
            append_run(paths, background["project_id"], value)
            print_result(value, args.json)
            return 2

    adb = adb_executable()
    if not adb:
        value = result(False, operation, 127, project_id=background["project_id"], background_id=background["background_id"], first_failure="ADB executable not found; set EMBEDDED_AGENT_ADB or add adb to PATH")
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 127

    devices_backend, devices = adb_devices(adb, args.timeout)
    if not devices_backend.get("ok"):
        value = result(False, operation, int(devices_backend.get("exit_code", 1)), project_id=background["project_id"], background_id=background["background_id"], backend=devices_backend, first_failure=devices_backend.get("first_failure") or "ADB device enumeration failed")
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return int(value["exit_code"])

    if args.device_action == "list":
        value = result(True, operation, project_id=background["project_id"], background_id=background["background_id"], read_only=True, devices=devices)
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 0

    device_serial, selection_error = select_adb_device(devices, args.serial)
    if selection_error or not device_serial:
        value = result(False, operation, 4, project_id=background["project_id"], background_id=background["background_id"], tty=tty_name, devices=devices, first_failure=selection_error)
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 4

    assert tty_name is not None
    tty_path = f"/dev/{tty_name}"
    sysfs_path = f"/sys/class/tty/{tty_name}/device"
    node_probe = run_adb(adb, ["-s", device_serial, "shell", "ls", "-l", tty_path], args.timeout)
    if not node_probe.get("ok"):
        value = result(False, operation, 4, project_id=background["project_id"], background_id=background["background_id"], device_serial=device_serial, tty=tty_name, read_only=True, backend=node_probe, first_failure=f"TTY node not found: {tty_path}")
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 4
    device_probe = run_adb(adb, ["-s", device_serial, "shell", "readlink", "-f", sysfs_path], args.timeout)
    driver_probe = run_adb(adb, ["-s", device_serial, "shell", "readlink", "-f", f"{sysfs_path}/driver"], args.timeout)
    uevent_probe = run_adb(adb, ["-s", device_serial, "shell", "cat", f"{sysfs_path}/uevent"], args.timeout)
    holder_probe = run_adb(adb, ["-s", device_serial, "shell", "ls", "-l", "/proc/[0-9]*/fd/*"], args.timeout)

    holders: list[dict[str, Any]] = []
    holder_pattern = re.compile(rf"/proc/(?P<pid>\d+)/fd/(?P<fd>\d+).*->\s*{re.escape(tty_path)}(?:\s|$)")
    clean_holder_output = ANSI_ESCAPE_PATTERN.sub("", str(holder_probe.get("stdout") or ""))
    for line in clean_holder_output.splitlines():
        match = holder_pattern.search(line)
        if not match:
            continue
        pid = match.group("pid")
        cmdline_probe = run_adb(adb, ["-s", device_serial, "shell", "cat", f"/proc/{pid}/cmdline"], args.timeout)
        command = str(cmdline_probe.get("stdout") or "").replace("\x00", " ").strip()
        holders.append({"pid": int(pid), "fd": int(match.group("fd")), "command": command or None})

    uevent: dict[str, str] = {}
    for line in str(uevent_probe.get("stdout") or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            uevent[key] = value

    value = result(
        True,
        operation,
        project_id=background["project_id"],
        background_id=background["background_id"],
        read_only=True,
        device_serial=device_serial,
        tty=tty_name,
        node=ANSI_ESCAPE_PATTERN.sub("", str(node_probe.get("stdout") or "")),
        sysfs_device=str(device_probe.get("stdout") or "") or None,
        driver=str(driver_probe.get("stdout") or "") or None,
        uevent=uevent,
        holders=holders,
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return 0
