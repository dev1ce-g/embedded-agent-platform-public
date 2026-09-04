"""Internal embedded runtime operations module."""

from __future__ import annotations

from embedded_runtime_common import *
from embedded_runtime_aboot import run_aboot_flash
from embedded_runtime_knowledge import compare_background_fingerprints
from embedded_runtime_sdk import mapping_kind

def command_build(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(False, "build", 2, first_failure="Project background not found")
        print_result(value, args.json)
        return 2
    targets = background.get("targets", {})
    background_target = background_target_name(args.target)
    if background_target not in targets:
        value = result(False, "build", 2, project_id=background["project_id"], target=args.target, first_failure="Target not in background")
        print_result(value, args.json)
        return 2
    target_build = targets.get(background_target, {}).get("build", {})
    if background_target == "mcu" and (target_build.get("method") == "keil" or not args.dry_run):
        selection_status = target_build.get(
            "selection_status",
            "selected" if target_build.get("project") else "missing",
        )
        selection_source = target_build.get("selection_source")
        selection_valid = (
            selection_status == "selected"
            and bool(target_build.get("project"))
            and selection_source in {"explicit", "existing_background"}
        )
        if not selection_valid:
            if selection_status == "selected":
                selection_status = "confirmation_required"
            value = result(
                False,
                "build",
                5,
                project_id=background["project_id"],
                target=args.target,
                background_id=background["background_id"],
                blocked=True,
                gate="keil-project-selection",
                requires_user_selection=True,
                selection_status=selection_status,
                selection_candidates=target_build.get("selection_candidates", []),
                first_failure="Keil build requires a user-selected project in project background",
            )
            append_run(paths, background["project_id"], value)
            print_result(value, args.json)
            return 5
    sdk_mapping = None
    if args.sdk_path:
        workspace = Path(background["workspace"])
        info = resolve_sdk_target(workspace, args.sdk_path)
        mapping_file = sdk_mappings_path(paths, background["project_id"])
        try:
            mapping_data = json.loads(mapping_file.read_text(encoding="utf-8"))
            sdk_mapping = (mapping_data.get("mappings") or {}).get(info["project_path"])
        except (OSError, json.JSONDecodeError):
            sdk_mapping = None
        mapping_valid = bool(info["inside_workspace"] and info["path"].is_dir() and isinstance(sdk_mapping, dict) and sdk_mapping.get("verified"))
        if mapping_valid and sdk_mapping.get("mode") == "junction":
            mapping_valid = mapping_kind(info["path"]) in {"junction", "symlink"} and info["path"].resolve() == Path(sdk_mapping["source"]).resolve()
        elif mapping_valid and sdk_mapping.get("mode") == "copy":
            mapping_valid = mapping_kind(info["path"]) == "directory"
        if not mapping_valid:
            value = result(
                False,
                "build",
                6,
                project_id=background["project_id"],
                target=args.target,
                background_id=background["background_id"],
                sdk_path=args.sdk_path,
                blocked=True,
                first_failure="SDK_MAPPING_REQUIRED",
                next_hint="Run embedded-agent sdk materialize, then sdk check-mapping before build",
            )
            append_run(paths, background["project_id"], value)
            print_result(value, args.json)
            return 6
    if args.dry_run:
        backend = result(
            True,
            f"build-{args.target}",
            workspace=background["workspace"],
            project=target_build.get("project"),
            dry_run=True,
        )
    else:
        backend_target = "mcu" if background_target == "mcu" else background_target
        agentctl_args = ["build", backend_target, "--workspace", background["workspace"]]
        if background_target == "mcu":
            agentctl_args.extend(["--project-path", target_build["project"]])
            if target_build.get("target"):
                agentctl_args.extend(["--keil-target", target_build["target"]])
            if target_build.get("output"):
                agentctl_args.extend(["--artifact-name", target_build["output"]])
            if target_build.get("output_directory"):
                agentctl_args.extend(["--output-directory", target_build["output_directory"]])
        backend = run_agentctl(args, agentctl_args)
    value = result(
        bool(backend.get("ok")),
        "build",
        int(backend.get("exit_code", 0 if backend.get("ok") else 1)),
        project_id=background["project_id"],
        target=args.target,
        background_id=background["background_id"],
        sdk_mapping=sdk_mapping,
        backend=backend,
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def command_log_tail(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(False, "log-tail", 2, first_failure="Project background not found")
        print_result(value, args.json)
        return 2
    if args.dry_run:
        backend = result(True, "log-tail", kind=args.kind, since=args.since, dry_run=True)
    else:
        backend = run_agentctl(args, ["log", "tail", "--kind", args.kind, "--since", args.since])
    value = result(
        bool(backend.get("ok")),
        "log-tail",
        int(backend.get("exit_code", 0 if backend.get("ok") else 1)),
        project_id=background["project_id"],
        background_id=background["background_id"],
        kind=args.kind,
        backend=backend,
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def command_log_import(args: argparse.Namespace) -> int:
    operation = "log-import"
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        print_result(result(False, operation, 2, project_id=safe_project_id(args.project), first_failure="Project background not found"), args.json)
        return 2
    if not valid_log_identifier(args.task, 80) or not valid_log_identifier(args.label, 64):
        value = result(False, operation, 2, project_id=background["project_id"], first_failure="--task and --label must contain only letters, digits, dots, dashes or underscores")
        print_result(value, args.json)
        return 2
    if not args.confirm:
        value = result(
            False,
            operation,
            3,
            project_id=background["project_id"],
            task=args.task,
            label=args.label,
            source_path=args.source,
            requires_human_confirm=True,
            gate={"level": "L1", "confirmed": False},
            first_failure="Log import copies a Desktop file into the private evidence store; rerun with --confirm",
        )
        print_result(value, args.json)
        return 3

    source, source_info, source_failure = resolve_log_import_source(args.source)
    if source_failure:
        value = result(False, operation, 5, project_id=background["project_id"], task=args.task, label=args.label, **source_info, first_failure=source_failure)
        print_result(value, args.json)
        return 5
    assert source is not None
    max_bytes = min(MAX_LOG_IMPORT_BYTES, max(1, args.max_bytes))
    try:
        with source.open("rb") as handle:
            sample = handle.read(DEFAULT_READ_BYTES)
    except OSError as exc:
        value = result(False, operation, 4, project_id=background["project_id"], source_path=str(source), first_failure=f"Cannot read log source: {exc}")
        print_result(value, args.json)
        return 4
    _, encoding, binary = decode_text(sample, args.encoding)
    if binary:
        value = result(False, operation, 4, project_id=background["project_id"], source_path=str(source), encoding=encoding, first_failure="Log import accepts text logs only")
        print_result(value, args.json)
        return 4

    objects = log_objects_dir(paths, background["project_id"])
    temporary_destination = objects / f"pending-{uuid.uuid4().hex}.log"
    copied, copy_failure = copy_log_source(source, temporary_destination, max_bytes)
    if copy_failure:
        value = result(False, operation, 4, project_id=background["project_id"], task=args.task, label=args.label, source_path=str(source), max_bytes=max_bytes, first_failure=copy_failure)
        print_result(value, args.json)
        return 4
    assert copied is not None

    digest = copied["sha256"]
    content = objects / f"{digest}.log"
    object_already_present = content.exists()
    try:
        if object_already_present:
            existing_digest = sha256_file(content)
            if existing_digest != digest:
                raise OSError("log artifact object collision")
            temporary_destination.unlink(missing_ok=True)
        else:
            content.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_destination, content)
    except OSError as exc:
        try:
            temporary_destination.unlink(missing_ok=True)
        except OSError:
            pass
        value = result(False, operation, 4, project_id=background["project_id"], task=args.task, label=args.label, first_failure=f"Cannot publish imported log: {exc}")
        print_result(value, args.json)
        return 4

    artifact_id = log_artifact_id(args.task, args.label, digest)
    record_path = log_record_path(paths, background["project_id"], artifact_id)
    assert record_path is not None
    existing_record, _, existing_failure = load_log_artifact(paths, background["project_id"], artifact_id)
    if existing_record is not None:
        if existing_record.get("sha256") != digest:
            value = result(False, operation, 4, project_id=background["project_id"], artifact_id=artifact_id, first_failure="Existing log record has a different SHA-256")
            print_result(value, args.json)
            return 4
        record = existing_record
        already_recorded = True
    elif existing_failure not in {"Log artifact record was not found", "Log artifact content is missing or invalid"}:
        value = result(False, operation, 4, project_id=background["project_id"], artifact_id=artifact_id, first_failure=existing_failure)
        print_result(value, args.json)
        return 4
    else:
        record = {
            "schema_version": LOG_ARTIFACT_SCHEMA_VERSION,
            "artifact_id": artifact_id,
            "project_id": background["project_id"],
            "task": args.task,
            "label": args.label,
            "content_path": f"objects/{content.name}",
            "sha256": digest,
            "size": copied["size"],
            "line_count": copied["line_count"],
            "encoding": encoding,
            "imported_at": now_iso(),
            "source": {
                "path": str(source),
                "mtime": copied["mtime"],
            },
        }
        try:
            write_json(record_path, record)
        except OSError as exc:
            value = result(False, operation, 4, project_id=background["project_id"], artifact_id=artifact_id, first_failure=f"Cannot write log artifact record: {exc}")
            print_result(value, args.json)
            return 4
        already_recorded = False

    value = result(
        True,
        operation,
        project_id=background["project_id"],
        background_id=background["background_id"],
        artifact_id=artifact_id,
        task=record["task"],
        label=record["label"],
        source=record["source"],
        stored_path=str(content),
        size=record["size"],
        line_count=record["line_count"],
        encoding=record["encoding"],
        sha256=record["sha256"],
        verified=True,
        already_present=object_already_present,
        already_recorded=already_recorded,
        gate={"level": "L1", "confirmed": True},
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return 0

def log_artifact_for_command(args: argparse.Namespace, operation: str) -> tuple[AgentPaths | None, dict[str, Any] | None, dict[str, Any] | None, Path | None]:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        print_result(result(False, operation, 2, project_id=safe_project_id(args.project), first_failure="Project background not found"), args.json)
        return None, None, None, None
    record, content, failure = load_log_artifact(paths, background["project_id"], args.artifact)
    if failure:
        print_result(result(False, operation, 2, project_id=background["project_id"], artifact_id=args.artifact, first_failure=failure), args.json)
        return None, None, None, None
    assert content is not None and record is not None
    return paths, background, record, content

def command_log_stat(args: argparse.Namespace) -> int:
    operation = "log-stat"
    _, background, record, content = log_artifact_for_command(args, operation)
    if background is None or record is None or content is None:
        return 2
    metadata = file_metadata(content, include_hash=True)
    integrity_verified = metadata.get("sha256") == record.get("sha256")
    value = result(
        integrity_verified,
        operation,
        0 if integrity_verified else 4,
        project_id=background["project_id"],
        artifact_id=record["artifact_id"],
        task=record["task"],
        label=record["label"],
        source=record["source"],
        encoding=record["encoding"],
        line_count=record["line_count"],
        expected_sha256=record["sha256"],
        integrity_verified=integrity_verified,
        **metadata,
    )
    if not integrity_verified:
        value["first_failure"] = "Log artifact SHA-256 does not match its import record"
    print_result(value, args.json)
    return int(value["exit_code"])

def command_log_read(args: argparse.Namespace) -> int:
    operation = "log-read"
    _, background, record, content = log_artifact_for_command(args, operation)
    if background is None or record is None or content is None:
        return 2
    size = content.stat().st_size
    offset = max(0, args.offset)
    max_bytes = min(MAX_LOG_QUERY_BYTES, max(1, args.max_bytes))
    try:
        with content.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(max_bytes)
    except OSError as exc:
        value = result(False, operation, 4, project_id=background["project_id"], artifact_id=record["artifact_id"], first_failure=f"Cannot read log artifact: {exc}")
        print_result(value, args.json)
        return 4
    text, encoding, binary = decode_text(data, args.encoding)
    value = result(
        True,
        operation,
        project_id=background["project_id"],
        artifact_id=record["artifact_id"],
        label=record["label"],
        offset=offset,
        bytes_read=len(data),
        size=size,
        encoding=encoding,
        binary=binary,
        truncated=(offset + len(data)) < size,
    )
    if binary or text is None:
        if args.binary:
            value["content_b64"] = base64.b64encode(data).decode("ascii")
        else:
            value["first_failure"] = "Log chunk appears to be binary; pass --binary to return content_b64"
    else:
        value["content"] = text
    print_result(value, args.json)
    return 0

def command_log_rg(args: argparse.Namespace) -> int:
    operation = "log-rg"
    _, background, record, content = log_artifact_for_command(args, operation)
    if background is None or record is None or content is None:
        return 2
    max_bytes = min(MAX_LOG_QUERY_BYTES, max(1, args.max_bytes))
    text, encoding, binary, bytes_read = read_text_file(content, args.encoding, max_bytes)
    if binary or text is None:
        value = result(False, operation, 4, project_id=background["project_id"], artifact_id=record["artifact_id"], encoding=encoding, first_failure="Cannot search binary log artifact")
        print_result(value, args.json)
        return 4
    try:
        flags = re.IGNORECASE if args.ignore_case else 0
        pattern = re.compile(args.pattern if args.regex else re.escape(args.pattern), flags)
    except re.error as exc:
        value = result(False, operation, 2, project_id=background["project_id"], artifact_id=record["artifact_id"], first_failure=f"Invalid search pattern: {exc}")
        print_result(value, args.json)
        return 2
    max_count = max(1, args.max_count)
    matches: list[dict[str, Any]] = []
    match_count = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        found = pattern.search(line)
        if not found:
            continue
        match_count += 1
        if len(matches) < max_count:
            matches.append({"line": line_number, "column": found.start() + 1, "text": bounded_text(line.strip())})
    value = result(
        True,
        operation,
        project_id=background["project_id"],
        artifact_id=record["artifact_id"],
        label=record["label"],
        pattern=args.pattern,
        regex=args.regex,
        ignore_case=args.ignore_case,
        encoding=encoding,
        bytes_read=bytes_read,
        size=content.stat().st_size,
        match_count=match_count,
        matches=matches,
        truncated=bytes_read < content.stat().st_size or match_count > len(matches),
        backend="python",
    )
    print_result(value, args.json)
    return 0

def command_log_context(args: argparse.Namespace) -> int:
    operation = "log-context"
    _, background, record, content = log_artifact_for_command(args, operation)
    if background is None or record is None or content is None:
        return 2
    if args.line < 1:
        value = result(False, operation, 2, project_id=background["project_id"], artifact_id=record["artifact_id"], first_failure="--line must be greater than zero")
        print_result(value, args.json)
        return 2
    max_bytes = min(MAX_LOG_QUERY_BYTES, max(1, args.max_bytes))
    text, encoding, binary, bytes_read = read_text_file(content, args.encoding, max_bytes)
    if binary or text is None:
        value = result(False, operation, 4, project_id=background["project_id"], artifact_id=record["artifact_id"], encoding=encoding, first_failure="Cannot read binary log artifact as context")
        print_result(value, args.json)
        return 4
    lines = text.splitlines()
    if args.line > len(lines):
        beyond_scan = bytes_read < content.stat().st_size
        value = result(
            False,
            operation,
            4 if beyond_scan else 2,
            project_id=background["project_id"],
            artifact_id=record["artifact_id"],
            line=args.line,
            bytes_read=bytes_read,
            first_failure="Requested line lies beyond the bounded scan" if beyond_scan else "Requested line does not exist",
            next_hint="Increase --max-bytes within the command limit" if beyond_scan else None,
        )
        print_result(value, args.json)
        return int(value["exit_code"])
    before = min(MAX_LOG_CONTEXT_LINES, max(0, args.before))
    after = min(MAX_LOG_CONTEXT_LINES, max(0, args.after))
    start = max(1, args.line - before)
    end = min(len(lines), args.line + after)
    context = [{"line": line_number, "text": bounded_text(lines[line_number - 1])} for line_number in range(start, end + 1)]
    value = result(
        True,
        operation,
        project_id=background["project_id"],
        artifact_id=record["artifact_id"],
        label=record["label"],
        encoding=encoding,
        requested_line=args.line,
        start_line=start,
        end_line=end,
        lines=context,
        bytes_read=bytes_read,
        size=content.stat().st_size,
        truncated=bytes_read < content.stat().st_size,
    )
    print_result(value, args.json)
    return 0

def command_log(args: argparse.Namespace) -> int:
    handlers = {
        "tail": command_log_tail,
        "import": command_log_import,
        "stat": command_log_stat,
        "read": command_log_read,
        "rg": command_log_rg,
        "context": command_log_context,
    }
    handler = handlers.get(args.log_action)
    if handler is None:
        print_result(result(False, "log", 2, first_failure=f"Unknown log action: {args.log_action}"), args.json)
        return 2
    return handler(args)

def command_rtt(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(False, "rtt-capture", 2, first_failure="Project background not found")
        print_result(value, args.json)
        return 2
    targets = background.get("targets", {})
    if args.target not in targets:
        value = result(False, "rtt-capture", 2, project_id=background["project_id"], target=args.target, first_failure="Target not in background")
        print_result(value, args.json)
        return 2
    stale_info = compare_background_fingerprints(background)
    if stale_info["stale"]:
        value = result(
            False,
            "rtt-capture",
            5,
            project_id=background["project_id"],
            target=args.target,
            background_id=background["background_id"],
            blocked=True,
            gate="background-stale",
            first_failure="Project background is stale; rerun project discover --write-background before RTT capture",
            **stale_info,
        )
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 5
    agentctl_args = [
        "rtt",
        "capture",
        "--workspace",
        background["workspace"],
        "--wait-ms",
        str(args.wait_ms),
    ]
    if args.reset:
        agentctl_args.append("--reset")
    backend = run_agentctl(args, agentctl_args)
    value = result(
        bool(backend.get("ok")),
        "rtt-capture",
        int(backend.get("exit_code", 0 if backend.get("ok") else 1)),
        project_id=background["project_id"],
        target=args.target,
        background_id=background["background_id"],
        gate={
            "background_stale": False,
            "mode": "reset" if args.reset else "attach",
        },
        backend=backend,
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def command_flash(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(False, "flash", 2, first_failure="Project background not found")
        print_result(value, args.json)
        return 2
    targets = background.get("targets", {})
    if args.target not in targets:
        value = result(False, "flash", 2, project_id=background["project_id"], target=args.target, first_failure="Target not in background")
        print_result(value, args.json)
        return 2
    flash_capability = background.get("capabilities", {}).get("flash", {})
    if flash_capability.get("status") != "gated" or flash_capability.get("requires_human_confirm") is not True:
        value = result(
            False,
            "flash",
            5,
            project_id=background["project_id"],
            target=args.target,
            background_id=background["background_id"],
            blocked=True,
            gate="flash-capability",
            capability=flash_capability,
            first_failure="Flash capability is not gated in project background",
        )
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 5
    stale_info = compare_background_fingerprints(background)
    if stale_info["stale"]:
        value = result(
            False,
            "flash",
            5,
            project_id=background["project_id"],
            target=args.target,
            background_id=background["background_id"],
            blocked=True,
            gate="background-stale",
            first_failure="Project background is stale; rerun project discover --write-background before flashing",
            **stale_info,
        )
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 5
    target_build = targets.get(args.target, {}).get("build", {})
    flash_context: dict[str, Any] = {}
    if args.target == "mcu":
        selection_status = target_build.get(
            "selection_status",
            "selected" if target_build.get("project") else "missing",
        )
        selection_source = target_build.get("selection_source")
        selection_valid = (
            selection_status == "selected"
            and bool(target_build.get("project"))
            and selection_source in {"explicit", "existing_background"}
        )
        if not selection_valid:
            if selection_status == "selected":
                selection_status = "confirmation_required"
            value = result(
                False,
                "flash",
                5,
                project_id=background["project_id"],
                target=args.target,
                background_id=background["background_id"],
                blocked=True,
                gate="mcu-keil-project-selection",
                requires_user_selection=True,
                selection_status=selection_status,
                selection_candidates=target_build.get("selection_candidates", []),
                first_failure="MCU flash requires a user-selected Keil project in project background",
            )
            append_run(paths, background["project_id"], value)
            print_result(value, args.json)
            return 5
        selected_project = next(
            (
                item
                for item in background.get("toolchains", {}).get("keil_projects", [])
                if item.get("path") == target_build.get("project")
            ),
            {},
        )
        flash_context["keil_selection"] = {
            "project": target_build.get("project"),
            "target": target_build.get("target"),
            "output": target_build.get("output"),
            "output_directory": target_build.get("output_directory"),
            "project_device": selected_project.get("device"),
            "output_kind": selected_project.get("output_kind"),
            "user_options": selected_project.get("user_options"),
        }
    if not args.require_confirm:
        value = result(False, "flash", 2, project_id=background["project_id"], target=args.target, requires_human_confirm=True, first_failure="Flash requires --require-confirm")
        print_result(value, args.json)
        return 2
    if not args.confirm:
        value = result(False, "flash", 3, project_id=background["project_id"], target=args.target, background_id=background["background_id"], blocked=True, requires_human_confirm=True, first_failure="Flash gate is closed until --confirm is supplied")
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 3
    if args.target == "mpu":
        if args.package is None:
            value = result(
                False,
                "flash",
                2,
                project_id=background["project_id"],
                target=args.target,
                background_id=background["background_id"],
                first_failure="MPU Aboot flash requires an explicit --package release ZIP",
            )
            append_run(paths, background["project_id"], value)
            print_result(value, args.json)
            return 2
        backend = run_aboot_flash(
            workspace=Path(background["workspace"]),
            package=args.package,
            aboot_root=args.aboot_root,
            firmware_root=args.firmware_root,
            ports=args.port,
            usb_only=args.usb_only,
            auto_enable=args.auto_enable,
            speed=args.speed,
            reboot=args.reboot,
            at_fallback=args.at_fallback,
            timeout=args.timeout,
            log_dir=paths.root / "logs",
        )
    else:
        agentctl_args = [
            "flash",
            args.target,
            "--workspace",
            background["workspace"],
            "--project-path",
            target_build["project"],
            "--require-confirm",
            "--confirm",
        ]
        if target_build.get("target"):
            agentctl_args.extend(["--keil-target", target_build["target"]])
        if target_build.get("output"):
            agentctl_args.extend(["--artifact-name", target_build["output"]])
        if target_build.get("output_directory"):
            agentctl_args.extend(["--output-directory", target_build["output_directory"]])
        backend = run_agentctl(args, agentctl_args)
    value = result(
        bool(backend.get("ok")),
        "flash",
        int(backend.get("exit_code", 0 if backend.get("ok") else 1)),
        project_id=background["project_id"],
        target=args.target,
        background_id=background["background_id"],
        gate={
            "level": "L3",
            "background_stale": False,
            "requires_human_confirm": True,
            "confirmed": True,
        },
        backend=backend,
        **flash_context,
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])
