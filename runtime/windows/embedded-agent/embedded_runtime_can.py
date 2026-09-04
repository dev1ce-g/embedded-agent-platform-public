"""Controlled CAN Runtime commands and hardware-operation gates."""

from __future__ import annotations

from embedded_runtime_common import *


CAN_BIN = Path(__file__).resolve().parent.parent / "bin"
CAN_TOOL = CAN_BIN / "pc_can_tool.py"
CAN_MIDDLEWARE = CAN_BIN / "can_middleware.py"
CAN_PROBE_TOOLS = {
    "controlcan": CAN_BIN / "probe-controlcan.py",
    "zcanpro": CAN_BIN / "probe-zcanpro.py",
}
CAN_DEVICE_MODELS = {
    "controlcan": (3, 4, 20, 21, 31, 34, 17, 32, 36, 37, 47),
    "zcanpro": (3, 4, 20, 21, 31, 34, 38, 39, 40, 41, 42, 43, 59, 60, 61, 62, 63, 76, 82, 83, 84, 85),
}


def _load_middleware() -> Any:
    if str(CAN_BIN) not in sys.path:
        sys.path.insert(0, str(CAN_BIN))
    import can_middleware

    return can_middleware


def _append_option(command: list[str], name: str, value: Any) -> None:
    if value is not None:
        command.extend([name, str(value)])


def _common_tool_args(args: argparse.Namespace) -> list[str]:
    values = ["--driver", args.driver, "--channel", str(args.channel), "--bitrate", str(args.bitrate)]
    _append_option(values, "--dll", args.dll)
    _append_option(values, "--device-model", args.device_model)
    _append_option(values, "--device-index", args.device_index)
    return values


def _run_tool(
    args: argparse.Namespace,
    tool_args: list[str],
    timeout: int,
    tool: Path = CAN_TOOL,
) -> dict[str, Any]:
    runtime = sys.executable
    driver = getattr(args, "driver", None)
    if driver:
        try:
            runtime = _load_middleware().driver_runtime(driver)
        except RuntimeError as exc:
            return result(False, "can-tool", 127, first_failure=str(exc))
    command = [runtime, str(tool), *tool_args]
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=max(1, timeout))
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_bytes, stdout_truncated = bounded_output(exc.stdout or b"", DEFAULT_READ_BYTES)
        stderr, stderr_bytes, stderr_truncated = bounded_output(exc.stderr or b"", DEFAULT_READ_BYTES)
        return result(False, "can-tool", 124, command=command, stdout=stdout, stderr=stderr, stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes, truncated=stdout_truncated or stderr_truncated, first_failure=f"CAN tool timed out after {timeout}s")
    except OSError as exc:
        return result(False, "can-tool", 127, command=command, first_failure=str(exc))
    stdout, stdout_bytes, stdout_truncated = bounded_output(completed.stdout, DEFAULT_READ_BYTES)
    stderr, stderr_bytes, stderr_truncated = bounded_output(completed.stderr, DEFAULT_READ_BYTES)
    failure_text = _failure_text(stderr, stdout)
    if completed.returncode != 0 and stdout:
        try:
            backend_result = _parse_backend_json(stdout)
        except ValueError:
            pass
        else:
            failure_text = backend_result.get("first_failure") or failure_text
    return result(completed.returncode == 0, "can-tool", completed.returncode, command=command, stdout=stdout, stderr=stderr, stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes, truncated=stdout_truncated or stderr_truncated, first_failure=None if completed.returncode == 0 else failure_text or "CAN tool failed")


def _failure_text(stderr: str, stdout: str) -> str | None:
    lines = [line.strip() for line in (stderr or stdout).splitlines() if line.strip()]
    failure_markers = ("error", "failed", "failure", "timeout", "mismatch", "nrc")
    return next((line for line in reversed(lines) if any(marker in line.lower() for marker in failure_markers)), lines[-1] if lines else None)


def _gate(args: argparse.Namespace, operation: str) -> dict[str, Any] | None:
    if not args.require_confirm:
        return result(False, operation, 2, requires_human_confirm=True, first_failure="CAN transmit operation requires --require-confirm")
    if not args.confirm:
        return result(False, operation, 3, requires_human_confirm=True, first_failure="CAN transmit gate is closed until a human passes --confirm")
    return None


def _parse_backend_json(stdout: str) -> dict[str, Any]:
    for line in stdout.splitlines():
        if line.lstrip().startswith("{"):
            return json.loads(line)
    raise ValueError("CAN probe did not emit a JSON object")


def command_can(args: argparse.Namespace) -> int:
    operation = f"can-{args.can_action}"
    middleware = _load_middleware()
    if args.can_action == "driver-list":
        value = result(True, operation, drivers=middleware.driver_inventory())
    elif args.can_action == "driver-probe":
        try:
            inventory = middleware.driver_inventory(args.driver)[0]
        except KeyError:
            value = result(False, operation, 2, driver=args.driver, first_failure=f"Unknown CAN driver: {args.driver}")
        else:
            value = result(bool(inventory["ready"]), operation, 0 if inventory["ready"] else 1, driver=inventory, first_failure=None if inventory["ready"] else "; ".join(inventory["blockers"]))
    elif args.can_action == "device-probe":
        inventory = middleware.driver_inventory(args.driver)[0]
        dll = args.dll or inventory.get("dll")
        models = args.device_model or [str(item) for item in CAN_DEVICE_MODELS[args.driver]]
        indexes = args.device_index or [0, 1, 2]
        probe_tool = CAN_PROBE_TOOLS.get(args.driver)
        if not dll:
            value = result(False, operation, 2, first_failure=f"{args.driver} driver DLL not found")
        elif probe_tool is None:
            value = result(False, operation, 2, first_failure=f"Device probe is not supported for driver: {args.driver}")
        else:
            backend = _run_tool(
                args,
                [
                    "discover",
                    "-Dll",
                    dll,
                    "-DevTypes",
                    ",".join(models),
                    "-DevIndexes",
                    ",".join(str(item) for item in indexes),
                    "-Json",
                ],
                args.timeout,
                probe_tool,
            )
            if not backend["ok"]:
                value = result(
                    False,
                    operation,
                    backend["exit_code"],
                    driver=args.driver,
                    dll=dll,
                    backend=backend,
                    first_failure=backend.get("first_failure"),
                )
            else:
                try:
                    probe = _parse_backend_json(backend["stdout"]) if backend.get("stdout") else {}
                except ValueError as exc:
                    value = result(False, operation, 1, driver=args.driver, dll=dll, backend=backend, first_failure=str(exc))
                    print_result(value, args.json)
                    return 1
                matches = [
                    {"device_model": item["type"], "device_index": item["index"]}
                    for item in probe.get("results", [])
                    if item.get("open") == 1 and (args.driver != "zcanpro" or item.get("physical") is True)
                ]
                value = result(
                    bool(matches),
                    operation,
                    0 if matches else 1,
                    driver=args.driver,
                    dll=dll,
                    candidates={"device_models": models, "device_indexes": indexes},
                    matches=matches,
                    backend=backend,
                    first_failure=None if matches else f"No {args.driver} device matched the bounded selector set",
                )
    elif args.can_action == "self-test":
        backend = _run_tool(args, ["self-test"], args.timeout)
        value = result(bool(backend["ok"]), operation, backend["exit_code"], backend=backend, first_failure=backend.get("first_failure"))
    elif args.can_action == "check-env":
        backend = _run_tool(args, ["check-env", *_common_tool_args(args)], args.timeout)
        value = result(bool(backend["ok"]), operation, backend["exit_code"], driver=args.driver, backend=backend, first_failure=backend.get("first_failure"))
    elif args.can_action == "monitor":
        if args.duration is None and args.count is None:
            value = result(False, operation, 2, first_failure="CAN monitor requires --duration or --count so the operation is bounded")
        else:
            tool_args = ["monitor", *_common_tool_args(args)]
            _append_option(tool_args, "--duration", args.duration)
            _append_option(tool_args, "--count", args.count)
            for can_id in args.can_id:
                tool_args.extend(["--id", can_id])
            for can_id in args.exclude_id:
                tool_args.extend(["--exclude-id", can_id])
            backend = _run_tool(args, tool_args, args.timeout)
            value = result(bool(backend["ok"]), operation, backend["exit_code"], driver=args.driver, backend=backend, first_failure=backend.get("first_failure"))
    else:
        if args.can_action == "uds-ecu" and args.idle_timeout is None and args.max_requests is None:
            value = result(False, operation, 2, first_failure="CAN UDS ECU requires --idle-timeout or --max-requests so the operation is bounded")
            print_result(value, args.json)
            return 2
        blocked = _gate(args, operation)
        if blocked:
            value = blocked
        else:
            tool_args = [args.can_action, *_common_tool_args(args)]
            if args.can_action == "send":
                for frame in args.frame:
                    tool_args.extend(["--frame", frame])
                tool_args.extend(["--count", str(args.count), "--period-ms", str(args.period_ms)])
            elif args.can_action == "uds-ecu":
                tool_args.extend(["--rxid", args.rxid, "--txid", args.txid, "--profile", args.profile])
                _append_option(tool_args, "--idle-timeout", args.idle_timeout)
                _append_option(tool_args, "--max-requests", args.max_requests)
            elif args.can_action == "uds-tester":
                tool_args.extend(["--rxid", args.rxid, "--txid", args.txid, "--response-timeout", str(args.response_timeout)])
                for request in args.request:
                    tool_args.extend(["--request", request])
                for expected in args.expect:
                    tool_args.extend(["--expect", expected])
            backend = _run_tool(args, tool_args, args.timeout)
            value = result(bool(backend["ok"]), operation, backend["exit_code"], driver=args.driver, gate={"level": "L3", "requires_human_confirm": True, "confirmed": True}, backend=backend, first_failure=backend.get("first_failure"))
    print_result(value, args.json)
    return int(value["exit_code"])
