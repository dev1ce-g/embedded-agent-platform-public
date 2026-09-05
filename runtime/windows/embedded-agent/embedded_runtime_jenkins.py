"""Internal embedded runtime jenkins module."""

from __future__ import annotations

from embedded_runtime_common import *
from embedded_runtime_knowledge import compare_background_fingerprints
from jenkins_client import (
    CONNECTION_ID_RE,
    JenkinsConnection,
    default_connection_registry_path,
    load_jenkins_connection,
    url_matches_connection_origin,
)
from job_runner import REQUEST_SCHEMA_VERSION, build_controlled_command

def jenkins_connection(args: argparse.Namespace) -> JenkinsConnection:
    return load_jenkins_connection(default_connection_registry_path(), args.connection_id)

def jenkins_client(args: argparse.Namespace, connection: JenkinsConnection | None = None) -> JenkinsClient:
    bound = connection or jenkins_connection(args)
    credentials = load_sdk_credentials(bound.credential_config, bound.server)
    return JenkinsClient(bound.server, credentials, timeout=args.timeout, connection_id=bound.connection_id)

def jenkins_failure(operation: str, args: argparse.Namespace, exc: JenkinsError) -> int:
    configuration_errors = {
        "AUTH_FAILED",
        "CREDENTIAL_CONFIG_NOT_FOUND",
        "CREDENTIAL_CONFIG_INVALID",
        "CREDENTIAL_FIELDS_NOT_FOUND",
        "CONNECTION_NOT_FOUND",
        "CONNECTION_REGISTRY_NOT_FOUND",
        "INVALID_CONNECTION",
        "INVALID_CONNECTION_ID",
        "INVALID_CONNECTION_REGISTRY",
    }
    exit_code = 4 if exc.code in configuration_errors else 1
    connection_id = getattr(args, "connection_id", None)
    value = result(
        False,
        operation,
        exit_code,
        connection_id=connection_id if isinstance(connection_id, str) else None,
        error_code=exc.code,
        http_status=exc.status,
        first_failure=str(exc),
    )
    print_result(value, args.json)
    return exit_code

def command_jenkins(args: argparse.Namespace) -> int:
    operation = f"jenkins-{args.jenkins_action}"
    if args.jenkins_action == "build-start" and not args.confirm:
        print_result(result(False, operation, 3, connection_id=args.connection_id, job=args.job, gate={"level": "CI_BUILD", "confirmed": False}, first_failure="Build trigger requires --confirm"), args.json)
        return 3
    try:
        client = jenkins_client(args)
        connection_info = {
            "connection_id": client.connection_id,
            "server": client.server,
            "credential_source": client.credentials.source,
            "credential_format": client.credentials.config_format,
        }
        if args.jenkins_action == "auth-check":
            auth = client.auth_check()
            print_result(result(True, operation, **connection_info, **auth), args.json)
            return 0
        if args.jenkins_action == "job-inspect":
            job = client.job(args.job)
            definitions = []
            for prop in job.get("property", []):
                definitions.extend(prop.get("parameterDefinitions", []) if isinstance(prop, dict) else [])
            value = result(True, operation, job=args.job, buildable=job.get("buildable"), in_queue=job.get("inQueue"), next_build_number=job.get("nextBuildNumber"), last_build=job.get("lastBuild"), last_completed_build=job.get("lastCompletedBuild"), parameter_definitions=definitions, **connection_info)
            print_result(value, args.json)
            return 0
        if args.jenkins_action == "parameters":
            data = client.build_parameters(args.job, args.build)
            print_result(result(True, operation, job=args.job, **data, **connection_info), args.json)
            return 0
        if args.jenkins_action in {"build-status", "build-wait"}:
            status = client.build_status(args.job, args.build) if args.jenkins_action == "build-status" else client.wait_for_completion(args.job, args.build, timeout=args.wait_timeout, interval=args.poll_interval)
            completed_result = status.get("result")
            wait_failed = args.jenkins_action == "build-wait" and completed_result != "SUCCESS"
            extra: dict[str, Any] = {}
            if wait_failed:
                extra["console_tail"] = client.console_tail(args.job, args.build, max_chars=args.max_chars)
                extra["first_failure"] = f"Jenkins build completed with result {completed_result or 'UNKNOWN'}"
            value = result(
                not wait_failed,
                operation,
                1 if wait_failed else 0,
                job=args.job,
                **status,
                **connection_info,
                **extra,
            )
            print_result(value, args.json)
            return int(value["exit_code"])
        if args.jenkins_action == "console-tail":
            console = client.console_tail(args.job, args.build, max_chars=args.max_chars)
            print_result(result(True, operation, job=args.job, build=args.build, console=console, **connection_info), args.json)
            return 0
        if args.jenkins_action == "build-start":
            source = client.build_parameters(args.job, args.from_build)
            parameters = dict(source["parameters"])
            changed = []
            for assignment in args.set_values:
                if "=" not in assignment:
                    print_result(result(False, operation, 2, first_failure=f"Invalid --set value: {assignment}"), args.json)
                    return 2
                name, value = assignment.split("=", 1)
                if name not in parameters:
                    print_result(result(False, operation, 2, first_failure=f"Parameter is absent from reference build: {name}"), args.json)
                    return 2
                parameters[name] = value
                changed.append(name)
            risky = sorted(name for name, value in parameters.items() if re.search(r"release|publish|deploy|sign|production|prod|flash", f"{name}={value}", re.IGNORECASE) and str(value).lower() not in {"", "0", "false", "none", "no"})
            if risky:
                print_result(result(False, operation, 3, connection_id=args.connection_id, server=client.server, job=args.job, gate={"level": "HIGH_RISK_CI", "confirmed": False}, risky_parameters=risky, first_failure="Release/signing/deployment-like parameters require a separate high-risk authorization"), args.json)
                return 3
            queued = client.start_build(args.job, parameters)
            build_number = client.wait_for_build_number(queued["queue_url"], timeout=args.queue_timeout)
            value = result(True, operation, job=args.job, reference_build=args.from_build, changed_parameters=changed, queue_url=queued["queue_url"], build_number=build_number, gate={"level": "CI_BUILD", "confirmed": True}, **connection_info)
            print_result(value, args.json)
            return 0
        print_result(result(False, operation, 2, first_failure="Unknown Jenkins action"), args.json)
        return 2
    except JenkinsError as exc:
        return jenkins_failure(operation, args, exc)

def command_artifact(args: argparse.Namespace) -> int:
    operation = "artifact-download"
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(False, operation, 2, project_id=safe_project_id(args.project), first_failure="Project background not found")
        print_result(value, args.json)
        return 2
    try:
        parsed_url = urlsplit(args.url)
    except ValueError:
        parsed_url = None
    if (
        parsed_url is None
        or parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        value = result(False, operation, 2, project_id=background["project_id"], first_failure="Artifact URL must be HTTP(S) without embedded credentials")
        print_result(value, args.json)
        return 2
    try:
        connection = jenkins_connection(args)
    except JenkinsError as exc:
        return jenkins_failure(operation, args, exc)
    if not url_matches_connection_origin(args.url, connection):
        value = result(
            False,
            operation,
            2,
            project_id=background["project_id"],
            connection_id=connection.connection_id,
            server=connection.server,
            first_failure="Artifact URL must use the configured connection origin",
        )
        print_result(value, args.json)
        return 2
    target_info = resolve_tool_path(background, args.to)
    if not target_info["inside_workspace"]:
        return fail_outside_workspace(operation, background, target_info, args.json)
    target = Path(target_info["path"])
    if target.exists() and not target.is_file():
        value = result(False, operation, 4, project_id=background["project_id"], target=target_info["project_path"], first_failure="Artifact target exists and is not a file")
        print_result(value, args.json)
        return 4
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
        value = result(False, operation, 2, project_id=background["project_id"], target=target_info["project_path"], first_failure="--sha256 must be a full 64-character SHA-256 digest")
        print_result(value, args.json)
        return 2
    if target.is_file():
        actual_sha256 = sha256_file(target)
        if actual_sha256 and actual_sha256.lower() == args.sha256.lower():
            value = result(True, operation, project_id=background["project_id"], workspace=background["workspace"], connection_id=connection.connection_id, server=connection.server, target=target_info["project_path"], normalized_path=str(target), size=target.stat().st_size, sha256=actual_sha256, verified=True, already_present=True, downloaded=False)
            print_result(value, args.json)
            return 0
        value = result(False, operation, 4, project_id=background["project_id"], target=target_info["project_path"], normalized_path=str(target), first_failure="Artifact target already exists with a different SHA-256")
        print_result(value, args.json)
        return 4
    if not args.confirm:
        value = result(False, operation, 3, project_id=background["project_id"], target=target_info["project_path"], requires_human_confirm=True, gate={"level": "L2", "confirmed": False}, first_failure="Artifact download writes to the Windows workspace; rerun with --confirm")
        print_result(value, args.json)
        return 3
    try:
        client = jenkins_client(args, connection)
        downloaded = client.download_artifact(args.url, target, args.sha256, max(1, args.max_bytes))
        value = result(
            True,
            operation,
            project_id=background["project_id"],
            background_id=background.get("background_id"),
            workspace=background["workspace"],
            connection_id=connection.connection_id,
            server=connection.server,
            target=target_info["project_path"],
            normalized_path=str(target),
            downloaded=True,
            already_present=False,
            credential_source=client.credentials.source,
            credential_format=client.credentials.config_format,
            gate={"level": "L2", "confirmed": True},
            **downloaded,
        )
        append_run(paths, background["project_id"], value)
        print_result(value, args.json)
        return 0
    except JenkinsError as exc:
        return jenkins_failure(operation, args, exc)

def read_runtime_job(paths: AgentPaths, job_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    directory = runtime_job_dir(paths, job_id)
    if directory is None:
        return None, None
    try:
        status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return directory, None
    return directory, status if isinstance(status, dict) else None

def runtime_job_spec(args: argparse.Namespace) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Normalize CLI inputs into the only persisted Job request parameters."""
    if args.kind == "build":
        if not args.target:
            return None, None, "build jobs require --target"
        target = "keil" if args.target == "mcu" else args.target
        parameters = {"target": target, "sdk_path": args.sdk_path}
        return parameters, f"{safe_project_id(args.project)}:build:{target}", None
    if args.kind == "jenkins-wait":
        if not args.jenkins_job or args.build is None:
            return None, None, "jenkins-wait jobs require --job and --build"
        if not isinstance(args.connection_id, str) or not CONNECTION_ID_RE.fullmatch(args.connection_id):
            return None, None, "jenkins-wait jobs require a valid --connection-id"
        parameters = {
            "connection_id": args.connection_id,
            "timeout": max(1, args.timeout),
            "job": args.jenkins_job,
            "build": args.build,
            "wait_timeout": max(1, args.wait_timeout),
            "poll_interval": max(1, args.poll_interval),
            "max_chars": max(1, args.max_chars),
        }
        operation_key = f"{safe_project_id(args.project)}:jenkins-wait:{args.connection_id}:{args.jenkins_job}:{args.build}"
        return parameters, operation_key, None
    return None, None, "Unsupported job kind"

def runtime_job_command(args: argparse.Namespace) -> tuple[list[str] | None, str | None, str | None]:
    """Compatibility helper that previews the fixed command rebuilt by the runner."""
    parameters, operation_key, failure = runtime_job_spec(args)
    if failure or parameters is None or operation_key is None:
        return None, None, failure or "Invalid job request"
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "job_id": "preview",
        "project_id": safe_project_id(args.project),
        "background_id": "preview",
        "kind": args.kind,
        "operation_key": operation_key,
        "parameters": parameters,
    }
    try:
        command = build_controlled_command(
            request,
            root=args.root,
        )
    except ValueError as exc:
        return None, None, str(exc)
    return command, operation_key, None

def active_runtime_job(paths: AgentPaths, operation_key: str) -> dict[str, Any] | None:
    if not paths.jobs.is_dir():
        return None
    for directory in paths.jobs.iterdir():
        if not directory.is_dir():
            continue
        try:
            status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status.get("operation_key") == operation_key and status.get("state") in {"queued", "running"}:
            return status
    return None

def launch_runtime_job_runner(job_dir: Path) -> subprocess.Popen[bytes]:
    runner = Path(__file__).resolve().with_name("job_runner.py")
    if not runner.is_file():
        raise OSError(f"Runtime job runner not found: {runner}")
    command = [
        sys.executable,
        str(runner),
        "--job-dir",
        str(job_dir.resolve()),
    ]
    with (job_dir / "runner.log").open("ab") as runner_log:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": runner_log,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            )
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(command, **kwargs)

def wait_for_runtime_job_start(job_dir: Path, launcher: subprocess.Popen[bytes], timeout: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        try:
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status = {}
        if status.get("state") != "queued":
            return status
        exit_code = launcher.poll()
        if exit_code is not None:
            try:
                raw = (job_dir / "runner.log").read_bytes()[-8192:]
                message, _, _ = decode_text(raw)
            except OSError:
                message = ""
            status.update(
                {
                    "state": "failed",
                    "exit_code": exit_code,
                    "finished_at": now_iso(),
                    "first_failure": message.strip() or f"Runtime job runner exited during startup ({exit_code})",
                }
            )
            write_json(job_dir / "status.json", status)
            return status
        time.sleep(0.05)
    return status

def runtime_job_failure(args: argparse.Namespace, message: str, exit_code: int = 2, **fields: Any) -> int:
    value = result(False, f"job-{args.job_action}", exit_code, first_failure=message, **fields)
    print_result(value, args.json)
    return exit_code

def start_runtime_job(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        return runtime_job_failure(args, "Project background not found", project_id=safe_project_id(args.project))
    parameters, operation_key, failure = runtime_job_spec(args)
    if failure or parameters is None or operation_key is None:
        return runtime_job_failure(args, failure or "Invalid job request")
    if args.kind == "jenkins-wait":
        try:
            jenkins_connection(args)
        except JenkinsError as exc:
            return jenkins_failure("job-start", args, exc)
    if args.kind == "build":
        if background_target_name(args.target) not in background.get("targets", {}):
            return runtime_job_failure(args, "Target not in project background", project_id=background["project_id"], target=args.target)
        stale = compare_background_fingerprints(background)
        if stale["stale"]:
            return runtime_job_failure(args, "Project background is stale", 6, project_id=background["project_id"], stale=stale)
    duplicate = active_runtime_job(paths, operation_key)
    if duplicate:
        return runtime_job_failure(args, "Equivalent runtime job is already active", 4, active_job=duplicate)

    paths.jobs.mkdir(parents=True, exist_ok=True)
    job_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:10]}"
    job_dir = paths.jobs / job_id
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "job_id": job_id,
        "project_id": background["project_id"],
        "background_id": background.get("background_id"),
        "kind": args.kind,
        "operation_key": operation_key,
        "parameters": parameters,
    }
    try:
        build_controlled_command(
            request,
            root=paths.root,
        )
    except ValueError as exc:
        return runtime_job_failure(args, str(exc))
    job_dir.mkdir()
    status = {
        "schema_version": "embedded-runtime-job/v1",
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "job_id": job_id,
        "project_id": background["project_id"],
        "background_id": background.get("background_id"),
        "kind": args.kind,
        "operation_key": operation_key,
        "state": "queued",
        "created_at": now_iso(),
        "stdout_path": str(job_dir / "stdout.log"),
        "stderr_path": str(job_dir / "stderr.log"),
        "runner_log_path": str(job_dir / "runner.log"),
        "result_path": str(job_dir / "result.json"),
    }
    write_json(job_dir / "request.json", request)
    write_json(job_dir / "status.json", status)
    try:
        launcher = launch_runtime_job_runner(job_dir)
    except OSError as exc:
        status.update({"state": "failed", "exit_code": 127, "finished_at": now_iso(), "first_failure": str(exc)})
        write_json(job_dir / "status.json", status)
        return runtime_job_failure(args, str(exc), 127, job=status)
    started = wait_for_runtime_job_start(job_dir, launcher)
    if started.get("state") == "failed":
        return runtime_job_failure(
            args,
            str(started.get("first_failure") or "Runtime job runner failed during startup"),
            int(started.get("exit_code", 127)),
            job=started,
        )
    value = result(
        True,
        "job-start",
        project_id=background["project_id"],
        background_id=background.get("background_id"),
        job_id=job_id,
        kind=args.kind,
        request_schema_version=REQUEST_SCHEMA_VERSION,
        operation_key=operation_key,
        state=started.get("state", "queued"),
        launcher_pid=launcher.pid,
        job_dir=str(job_dir),
        gate={"level": "L1", "confirmed": True},
    )
    append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return 0

def show_runtime_job(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    directory, status = read_runtime_job(paths, args.job_id)
    if directory is None or status is None:
        return runtime_job_failure(args, "Runtime job not found", job_id=args.job_id)
    value = result(
        True,
        "job-status",
        phase="status",
        state=status.get("state", "succeeded"),
        job=status,
        job_dir=str(directory),
    )
    print_result(value, args.json)
    return 0

def output_runtime_job(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    directory, status = read_runtime_job(paths, args.job_id)
    if directory is None or status is None:
        return runtime_job_failure(args, "Runtime job not found", job_id=args.job_id)
    log_path = directory / f"{args.stream}.log"
    offset = max(0, args.offset)
    max_bytes = min(max(1, args.max_bytes), 1024 * 1024)
    try:
        size = log_path.stat().st_size
        with log_path.open("rb") as handle:
            handle.seek(min(offset, size))
            data = handle.read(max_bytes)
    except FileNotFoundError:
        size = 0
        data = b""
    except OSError as exc:
        return runtime_job_failure(args, str(exc), 4, job_id=args.job_id)
    text, encoding, binary = decode_text(data)
    next_offset = min(offset, size) + len(data)
    terminal = status.get("state") in {"succeeded", "failed", "canceled"}
    value = result(
        True,
        "job-output",
        phase="status",
        job_id=args.job_id,
        state=status.get("state"),
        stream=args.stream,
        offset=offset,
        next_offset=next_offset,
        total_bytes=size,
        encoding=encoding,
        binary=binary,
        content=None if binary else text,
        content_base64=base64.b64encode(data).decode("ascii") if binary else None,
        truncated=next_offset < size,
        eof=terminal and next_offset >= size,
    )
    print_result(value, args.json)
    return 0

def cancel_runtime_job(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    directory, status = read_runtime_job(paths, args.job_id)
    if directory is None or status is None:
        return runtime_job_failure(args, "Runtime job not found", job_id=args.job_id)
    if status.get("state") in {"succeeded", "failed", "canceled"}:
        value = result(True, "job-cancel", job_id=args.job_id, state=status.get("state"), already_terminal=True, cancel_requested=False)
        print_result(value, args.json)
        return 0
    if not args.confirm:
        return runtime_job_failure(args, "Canceling a runtime process requires --confirm", 3, job_id=args.job_id, requires_human_confirm=True, gate={"level": "L2", "confirmed": False})
    write_json(directory / "cancel.requested", {"job_id": args.job_id, "requested_at": now_iso()})
    value = result(True, "job-cancel", job_id=args.job_id, state=status.get("state"), cancel_requested=True, gate={"level": "L2", "confirmed": True})
    print_result(value, args.json)
    return 0

def list_runtime_jobs(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    jobs: list[dict[str, Any]] = []
    if paths.jobs.is_dir():
        for directory in paths.jobs.iterdir():
            if not directory.is_dir():
                continue
            try:
                status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if args.project and status.get("project_id") != safe_project_id(args.project):
                continue
            jobs.append(status)
    jobs.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    limit = min(max(1, args.limit), 200)
    value = result(True, "job-list", phase="status", project_id=safe_project_id(args.project) if args.project else None, job_count=len(jobs), jobs=jobs[:limit], truncated=len(jobs) > limit)
    print_result(value, args.json)
    return 0

def command_job(args: argparse.Namespace) -> int:
    if args.job_action == "start":
        return start_runtime_job(args)
    if args.job_action == "status":
        return show_runtime_job(args)
    if args.job_action == "output":
        return output_runtime_job(args)
    if args.job_action == "cancel":
        return cancel_runtime_job(args)
    if args.job_action == "list":
        return list_runtime_jobs(args)
    return runtime_job_failure(args, "Unknown runtime job action")
