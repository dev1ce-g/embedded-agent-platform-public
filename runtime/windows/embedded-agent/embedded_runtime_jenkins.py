"""Internal embedded runtime jenkins module."""

from __future__ import annotations

from embedded_runtime_common import *

def jenkins_client(args: argparse.Namespace) -> JenkinsClient:
    credentials = load_sdk_credentials(args.config, args.server)
    return JenkinsClient(args.server, credentials, timeout=args.timeout)

def jenkins_failure(operation: str, args: argparse.Namespace, exc: JenkinsError) -> int:
    exit_code = 4 if exc.code in {"AUTH_FAILED", "CREDENTIAL_FIELDS_NOT_FOUND"} else 1
    value = result(False, operation, exit_code, server=args.server, error_code=exc.code, http_status=exc.status, first_failure=str(exc))
    print_result(value, args.json)
    return exit_code

def command_jenkins(args: argparse.Namespace) -> int:
    operation = f"jenkins-{args.jenkins_action}"
    if args.jenkins_action == "build-start" and not args.confirm:
        print_result(result(False, operation, 3, server=args.server, job=args.job, gate={"level": "CI_BUILD", "confirmed": False}, first_failure="Build trigger requires --confirm"), args.json)
        return 3
    try:
        client = jenkins_client(args)
        credential_info = {"credential_source": client.credentials.source, "credential_format": client.credentials.config_format}
        if args.jenkins_action == "auth-check":
            auth = client.auth_check()
            print_result(result(True, operation, server=args.server, **credential_info, **auth), args.json)
            return 0
        if args.jenkins_action == "job-inspect":
            job = client.job(args.job)
            definitions = []
            for prop in job.get("property", []):
                definitions.extend(prop.get("parameterDefinitions", []) if isinstance(prop, dict) else [])
            value = result(True, operation, server=args.server, job=args.job, buildable=job.get("buildable"), in_queue=job.get("inQueue"), next_build_number=job.get("nextBuildNumber"), last_build=job.get("lastBuild"), last_completed_build=job.get("lastCompletedBuild"), parameter_definitions=definitions, **credential_info)
            print_result(value, args.json)
            return 0
        if args.jenkins_action == "parameters":
            data = client.build_parameters(args.job, args.build)
            print_result(result(True, operation, server=args.server, job=args.job, **data, **credential_info), args.json)
            return 0
        if args.jenkins_action in {"build-status", "build-wait"}:
            status = client.build_status(args.job, args.build) if args.jenkins_action == "build-status" else client.wait_for_completion(args.job, args.build, timeout=args.wait_timeout, interval=args.poll_interval)
            value = result(True, operation, server=args.server, job=args.job, **status, **credential_info)
            if args.jenkins_action == "build-wait" and status.get("result") != "SUCCESS":
                value["ok"] = False
                value["exit_code"] = 1
                value["console_tail"] = client.console_tail(args.job, args.build, max_chars=args.max_chars)
            print_result(value, args.json)
            return int(value["exit_code"])
        if args.jenkins_action == "console-tail":
            console = client.console_tail(args.job, args.build, max_chars=args.max_chars)
            print_result(result(True, operation, server=args.server, job=args.job, build=args.build, console=console, **credential_info), args.json)
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
                print_result(result(False, operation, 3, server=args.server, job=args.job, gate={"level": "HIGH_RISK_CI", "confirmed": False}, risky_parameters=risky, first_failure="Release/signing/deployment-like parameters require a separate high-risk authorization"), args.json)
                return 3
            queued = client.start_build(args.job, parameters)
            build_number = client.wait_for_build_number(queued["queue_url"], timeout=args.queue_timeout)
            value = result(True, operation, server=args.server, job=args.job, reference_build=args.from_build, changed_parameters=changed, queue_url=queued["queue_url"], build_number=build_number, gate={"level": "CI_BUILD", "confirmed": True}, **credential_info)
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
    parsed_url = urlsplit(args.url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc or parsed_url.username is not None:
        value = result(False, operation, 2, project_id=background["project_id"], first_failure="Artifact URL must be HTTP(S) without embedded credentials")
        print_result(value, args.json)
        return 2
    if not args.server:
        args.server = f"{parsed_url.scheme}://{parsed_url.netloc}"
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
            value = result(True, operation, project_id=background["project_id"], workspace=background["workspace"], target=target_info["project_path"], normalized_path=str(target), size=target.stat().st_size, sha256=actual_sha256, verified=True, already_present=True, downloaded=False)
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
        client = jenkins_client(args)
        downloaded = client.download_artifact(args.url, target, args.sha256, max(1, args.max_bytes))
        value = result(
            True,
            operation,
            project_id=background["project_id"],
            background_id=background.get("background_id"),
            workspace=background["workspace"],
            server=args.server,
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

def runtime_job_command(args: argparse.Namespace) -> tuple[list[str] | None, str | None, str | None]:
    agent_script = Path(__file__).resolve()
    prefix = [
        sys.executable,
        str(agent_script),
        "--root",
        str(args.root),
        "--agentctl",
        str(args.agentctl),
        "--sdk-manager",
        str(args.sdk_manager),
    ]
    if args.kind == "build":
        if not args.target:
            return None, None, "build jobs require --target"
        command = [*prefix, "build", "--project", args.project, "--target", args.target]
        if args.sdk_path:
            command.extend(["--sdk-path", args.sdk_path])
        command.append("--json")
        return command, f"{safe_project_id(args.project)}:build:{args.target}", None
    if args.kind == "jenkins-wait":
        if not args.jenkins_job or args.build is None:
            return None, None, "jenkins-wait jobs require --job and --build"
        if not valid_http_server_url(args.server):
            return None, None, "Jenkins server must be an HTTP(S) URL without embedded credentials, query or fragment"
        command = [
            *prefix,
            "jenkins",
            "--server",
            args.server,
            "--config",
            str(args.config),
            "--timeout",
            str(max(1, args.timeout)),
            "build-wait",
            "--job",
            args.jenkins_job,
            "--build",
            str(args.build),
            "--wait-timeout",
            str(max(1, args.wait_timeout)),
            "--poll-interval",
            str(max(1, args.poll_interval)),
            "--max-chars",
            str(max(1, args.max_chars)),
            "--json",
        ]
        return command, f"{safe_project_id(args.project)}:jenkins-wait:{args.jenkins_job}:{args.build}", None
    return None, None, "Unsupported job kind"

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
    command = [sys.executable, str(runner), "--job-dir", str(job_dir)]
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
    command, operation_key, failure = runtime_job_command(args)
    if failure or command is None or operation_key is None:
        return runtime_job_failure(args, failure or "Invalid job request")
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
    job_dir.mkdir()
    status = {
        "schema_version": "embedded-runtime-job/v1",
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
    request = {
        "schema_version": "embedded-runtime-job-request/v1",
        "job_id": job_id,
        "project_id": background["project_id"],
        "kind": args.kind,
        "operation_key": operation_key,
        "command": command,
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
    value = result(True, "job-status", job=status, job_dir=str(directory))
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
    value = result(True, "job-list", project_id=safe_project_id(args.project) if args.project else None, job_count=len(jobs), jobs=jobs[:limit], truncated=len(jobs) > limit)
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
