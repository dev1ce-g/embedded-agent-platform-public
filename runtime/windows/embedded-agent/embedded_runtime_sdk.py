"""Internal embedded runtime sdk module."""

from __future__ import annotations

from embedded_runtime_common import *
from embedded_runtime_knowledge import compare_background_fingerprints

def run_sdk_manager(
    args: argparse.Namespace,
    manager_args: list[str],
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    manager, trust_failure = trusted_sdk_manager()
    if manager is None:
        message = trust_failure or "SDK Manager capability unavailable"
        return {
            "ok": False,
            "exit_code": 126,
            "stdout": "",
            "stderr": message,
            "stdout_bytes": 0,
            "stderr_bytes": len(message.encode("utf-8", errors="replace")),
            "truncated": False,
            "capability_available": False,
            "first_failure": message,
        }
    command = [sys.executable, str(manager), *manager_args]
    environment = os.environ.copy()
    environment.pop("EMBEDDED_AGENTCTL", None)
    environment.pop("EMBEDDED_SDK_MANAGER", None)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(1, args.timeout),
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_bytes, stdout_truncated = bounded_output(exc.stdout, args.max_bytes)
        stderr, stderr_bytes, stderr_truncated = bounded_output(exc.stderr, args.max_bytes)
        return {
            "ok": False,
            "exit_code": 124,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "truncated": stdout_truncated or stderr_truncated,
            "first_failure": f"SDK Manager timed out after {max(1, args.timeout)}s",
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "stdout_bytes": 0,
            "stderr_bytes": len(str(exc).encode("utf-8", errors="replace")),
            "truncated": False,
            "first_failure": str(exc),
        }
    stdout, stdout_bytes, stdout_truncated = bounded_output(completed.stdout, args.max_bytes)
    stderr, stderr_bytes, stderr_truncated = bounded_output(completed.stderr, args.max_bytes)
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "truncated": stdout_truncated or stderr_truncated,
        "first_failure": stderr.strip() if completed.returncode != 0 and stderr.strip() else None,
    }

def sdk_workspace(args: argparse.Namespace, paths: AgentPaths) -> tuple[Path | None, dict[str, Any] | None]:
    background = read_background(paths, args.project)
    if background:
        return Path(background["workspace"]).resolve(), background
    return None, None

def read_sdk_lock(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def sdk_source(args: argparse.Namespace) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sdk):
        return None, None, "Invalid SDK name"
    component = Path(args.component)
    if component.is_absolute() or not args.component.strip():
        return None, None, "SDK component must be a relative path"
    store = DEFAULT_SDK_STORE.resolve()
    source = (store / "current" / args.sdk / component).resolve()
    versions = (store / "versions").resolve()
    if not is_relative_to(source, versions):
        return None, None, "SDK component does not resolve inside the managed versions store"
    if not source.is_dir():
        return None, None, "SDK component directory does not exist"
    lock = read_sdk_lock(DEFAULT_SDK_LOCK)
    if not lock:
        return None, None, "SDK lock is missing or invalid"
    package = (lock.get("packages") or {}).get(args.sdk)
    if not isinstance(package, dict):
        return None, None, "SDK is not present in sdk.lock"
    installed = package.get("installed_path")
    if not installed or not is_relative_to(source, Path(installed).resolve()):
        return None, None, "Current SDK component does not match the locked installed path"
    evidence = {
        "sdk": args.sdk,
        "version": package.get("version"),
        "archive_sha256": package.get("sha256"),
        "installed_path": str(Path(installed).resolve()),
        "component": Path(args.component).as_posix(),
        "source": str(source),
    }
    return source, evidence, None

def mapping_kind(path: Path) -> str:
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return "junction"
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    return "missing"

def sdk_mapping_record(
    target_info: dict[str, Any],
    target: Path,
    source: Path,
    sdk_evidence: dict[str, Any],
    mode: str,
    mapping_kind_value: str,
    resolved_target: Path | None,
    verified: bool,
) -> dict[str, Any]:
    return {
        "target": target_info["project_path"],
        "normalized_target": str(target),
        "mode": mode,
        "mapping_kind": mapping_kind_value,
        "source": str(source),
        "resolved_target": str(resolved_target) if resolved_target else None,
        "sdk": sdk_evidence,
        "verified": verified,
        "updated_at": now_iso(),
    }

def write_sdk_mapping(paths: AgentPaths, project: str, mapping: dict[str, Any]) -> None:
    path = sdk_mappings_path(paths, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, Any] = {"version": 1, "mappings": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            current = loaded
    except (OSError, json.JSONDecodeError):
        pass
    mappings = current.setdefault("mappings", {})
    mappings[mapping["target"]] = mapping
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sdk_mapping_command(args: argparse.Namespace, paths: AgentPaths, workspace: Path, background: dict[str, Any] | None) -> int:
    operation = f"sdk-{args.sdk_action}"
    project_id = background["project_id"] if background else safe_project_id(args.project)
    source, sdk_evidence, source_failure = sdk_source(args)
    if source_failure:
        value = result(False, operation, 4, project_id=project_id, workspace=str(workspace), first_failure=source_failure)
        print_result(value, args.json)
        return 4
    assert source is not None and sdk_evidence is not None
    target_info = resolve_sdk_target(workspace, args.to)
    if not target_info["inside_workspace"]:
        return fail_outside_workspace(operation, {"project_id": project_id, "workspace": str(workspace)}, target_info, args.json)
    target = target_info["path"]
    unsafe_ancestor, ancestor_failure = validate_non_reparse_ancestors(workspace, target)
    if ancestor_failure:
        value = result(
            False,
            operation,
            5,
            project_id=project_id,
            workspace=str(workspace),
            target=target_info["project_path"],
            normalized_target=str(target),
            unsafe_ancestor=str(unsafe_ancestor) if unsafe_ancestor else None,
            first_failure=ancestor_failure,
        )
        print_result(value, args.json)
        return 5
    kind = mapping_kind(target)
    resolved_target = target.resolve() if target.exists() else None
    link_valid = kind in {"junction", "symlink"} and resolved_target == source
    valid = args.mode == "junction" and link_valid
    recorded = None
    try:
        mapping_data = json.loads(sdk_mappings_path(paths, project_id).read_text(encoding="utf-8"))
        recorded = (mapping_data.get("mappings") or {}).get(target_info["project_path"])
    except (OSError, json.JSONDecodeError):
        pass
    if args.sdk_action == "check-mapping":
        copy_valid = bool(
            args.mode == "copy"
            and kind == "directory"
            and isinstance(recorded, dict)
            and recorded.get("verified")
            and recorded.get("mode") == "copy"
            and recorded.get("sdk", {}).get("sdk") == sdk_evidence["sdk"]
            and recorded.get("sdk", {}).get("version") == sdk_evidence["version"]
            and recorded.get("sdk", {}).get("component") == sdk_evidence["component"]
        )
        value = result(
            valid or copy_valid,
            operation,
            0 if valid or copy_valid else 6,
            project_id=project_id,
            workspace=str(workspace),
            target=target_info["project_path"],
            normalized_target=str(target),
            mapping_kind=kind,
            resolved_target=str(resolved_target) if resolved_target else None,
            valid=valid or copy_valid,
            sdk=sdk_evidence,
            recorded_mapping=recorded,
            first_failure=None if valid or copy_valid else "SDK_MAPPING_REQUIRED",
        )
        print_result(value, args.json)
        return int(value["exit_code"])
    if target.exists():
        if valid:
            mapping = sdk_mapping_record(target_info, target, source, sdk_evidence, args.mode, kind, resolved_target, True)
            if args.confirm:
                write_sdk_mapping(paths, project_id, mapping)
            value = result(
                True,
                operation,
                project_id=project_id,
                workspace=str(workspace),
                already_ready=True,
                mapping_recorded=bool(args.confirm),
                gate={"level": "L2", "requires_human_confirm": True, "confirmed": bool(args.confirm)},
                **mapping,
            )
            if background and args.confirm:
                append_run(paths, project_id, value)
            print_result(value, args.json)
            return 0
        replaceable = bool(
            args.replace_managed
            and args.mode == "junction"
            and kind in {"junction", "symlink"}
            and isinstance(recorded, dict)
            and recorded.get("verified")
            and recorded.get("mode") == "junction"
            and recorded.get("resolved_target") == str(resolved_target)
        )
        if replaceable:
            if not args.confirm:
                value = result(False, operation, 3, project_id=project_id, workspace=str(workspace), target=target_info["project_path"], requires_human_confirm=True, first_failure="Replacing a managed SDK mapping requires --confirm")
                print_result(value, args.json)
                return 3
            try:
                target.rmdir()
            except OSError as exc:
                value = result(False, operation, 4, project_id=project_id, workspace=str(workspace), target=target_info["project_path"], first_failure=f"Cannot remove managed SDK mapping: {exc}")
                print_result(value, args.json)
                return 4
            kind = "missing"
            resolved_target = None
        else:
            try:
                non_empty = target.is_dir() and any(target.iterdir())
            except OSError:
                non_empty = True
            if kind != "directory" or non_empty:
                value = result(False, operation, 4, project_id=project_id, workspace=str(workspace), target=target_info["project_path"], mapping_kind=kind, first_failure="SDK target already exists and is not an empty directory")
                print_result(value, args.json)
                return 4
    if not args.confirm:
        value = result(False, operation, 3, project_id=project_id, workspace=str(workspace), target=target_info["project_path"], requires_human_confirm=True, first_failure="SDK materialization changes the workspace; rerun with --confirm")
        print_result(value, args.json)
        return 3
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.rmdir()
    try:
        if args.mode == "copy":
            shutil.copytree(source, target)
        else:
            completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if completed.returncode != 0:
                stderr, _, _ = bounded_output(completed.stderr or completed.stdout, args.max_bytes)
                raise OSError(stderr.strip() or "mklink /J failed")
    except OSError as exc:
        value = result(False, operation, 4, project_id=project_id, workspace=str(workspace), target=target_info["project_path"], first_failure=str(exc))
        print_result(value, args.json)
        return 4
    actual_kind = mapping_kind(target)
    actual_resolved = target.resolve()
    verified = target.is_dir() and (args.mode == "copy" or actual_resolved == source)
    mapping = sdk_mapping_record(target_info, target, source, sdk_evidence, args.mode, actual_kind, actual_resolved, verified)
    if verified:
        write_sdk_mapping(paths, project_id, mapping)
    value = result(verified, operation, 0 if verified else 6, project_id=project_id, workspace=str(workspace), gate={"level": "L2", "requires_human_confirm": True, "confirmed": True}, **mapping, first_failure=None if verified else "SDK mapping verification failed")
    if background:
        append_run(paths, project_id, value)
    print_result(value, args.json)
    return int(value["exit_code"])

def command_sdk(args: argparse.Namespace) -> int:
    operation = f"sdk-{args.sdk_action}"
    manager, trust_failure = trusted_sdk_manager()
    manager_path = manager or DEFAULT_SDK_MANAGER
    config = manager_path.parent / "sdk.cfg"
    if args.sdk_action == "status":
        ready = manager is not None and config.is_file()
        value = result(
            ready,
            operation,
            0 if ready else 2,
            sdk_manager=str(manager_path),
            manager_exists=manager is not None,
            config_path=str(config),
            config_exists=config.is_file(),
            capability_available=manager is not None,
            first_failure=None if ready else trust_failure or "Runtime-owned SDK Manager configuration is missing",
        )
        print_result(value, args.json)
        return int(value["exit_code"])
    if args.sdk_action == "components":
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sdk):
            value = result(False, operation, 2, first_failure="Invalid SDK name")
            print_result(value, args.json)
            return 2
        component = Path(args.component)
        if component.is_absolute() or not args.component.strip():
            value = result(False, operation, 2, first_failure="SDK component must be a relative path")
            print_result(value, args.json)
            return 2
        store = DEFAULT_SDK_STORE.resolve()
        source = (store / "current" / args.sdk / component).resolve()
        versions = (store / "versions").resolve()
        if not is_relative_to(source, versions) or not source.is_dir():
            value = result(False, operation, 4, sdk=args.sdk, component=args.component, first_failure="SDK component directory does not exist inside managed store")
            print_result(value, args.json)
            return 4
        entries = []
        for child in sorted(source.iterdir(), key=lambda item: item.name.lower()):
            entries.append({"name": child.name, "kind": "directory" if child.is_dir() else "file"})
            if len(entries) >= min(max(1, args.max_entries), 500):
                break
        value = result(True, operation, sdk=args.sdk, component=Path(args.component).as_posix(), source=str(source), entries=entries, truncated=len(entries) >= min(max(1, args.max_entries), 500))
        print_result(value, args.json)
        return 0
    if args.sdk_action in {"list", "search"} and manager is None:
        value = result(
            False,
            operation,
            2,
            sdk_manager=str(manager_path),
            capability_available=False,
            first_failure=trust_failure or "SDK Manager capability unavailable",
        )
        print_result(value, args.json)
        return 2
    if args.sdk_action == "list":
        backend = run_sdk_manager(args, ["list"])
        value = result(bool(backend["ok"]), operation, int(backend["exit_code"]), sdk_manager=str(manager), backend=backend)
        print_result(value, args.json)
        return int(value["exit_code"])
    if args.sdk_action == "search":
        if len(args.query) > 200 or any(ch in args.query for ch in ("\r", "\n", "\x00")):
            value = result(False, operation, 2, first_failure="Invalid SDK search query")
            print_result(value, args.json)
            return 2
        backend = run_sdk_manager(args, ["search", args.query, "--limit", str(min(max(1, args.limit), 100))])
        value = result(bool(backend["ok"]), operation, int(backend["exit_code"]), query=args.query, backend=backend)
        print_result(value, args.json)
        return int(value["exit_code"])

    paths = agent_paths(args.root)
    workspace, background = sdk_workspace(args, paths)
    if workspace is None:
        value = result(False, operation, 2, project_id=safe_project_id(args.project), first_failure="Project background not found")
        print_result(value, args.json)
        return 2
    if not workspace.is_dir():
        value = result(False, operation, 4, project_id=safe_project_id(args.project), workspace=str(workspace), first_failure="SDK project workspace does not exist")
        print_result(value, args.json)
        return 4
    if args.sdk_action in {"project-pull", "materialize"} and background:
        stale = compare_background_fingerprints(background)
        if stale["stale"]:
            value = result(
                False,
                operation,
                6,
                project_id=background["project_id"],
                background_id=background.get("background_id"),
                workspace=str(workspace),
                blocked=True,
                stale=stale,
                first_failure="Project background is stale",
            )
            print_result(value, args.json)
            return 6
    if args.sdk_action in {"materialize", "check-mapping"}:
        return sdk_mapping_command(args, paths, workspace, background)
    if manager is None:
        value = result(
            False,
            operation,
            2,
            sdk_manager=str(manager_path),
            capability_available=False,
            first_failure=trust_failure or "SDK Manager capability unavailable",
        )
        print_result(value, args.json)
        return 2
    manager_args = ["project-sdk"]
    if args.ci_dir:
        ci_dir = Path(args.ci_dir).expanduser()
        if not ci_dir.is_absolute():
            ci_dir = workspace / ci_dir
        ci_dir = ci_dir.resolve()
        if not is_relative_to(ci_dir, workspace):
            value = result(False, operation, 5, project_id=safe_project_id(args.project), workspace=str(workspace), first_failure="CI directory is outside project workspace")
            print_result(value, args.json)
            return 5
        manager_args.extend(["--ci-dir", str(ci_dir)])
    if args.query:
        manager_args.extend(["--query", args.query])
    if args.sdk_name:
        if len(args.sdk_name) > 100 or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sdk_name):
            value = result(False, operation, 2, project_id=safe_project_id(args.project), workspace=str(workspace), first_failure="Invalid SDK name")
            print_result(value, args.json)
            return 2
        manager_args.extend(["--sdk-name", args.sdk_name])
    if args.sdk_version:
        if len(args.sdk_version) > 100 or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sdk_version):
            value = result(False, operation, 2, project_id=safe_project_id(args.project), workspace=str(workspace), first_failure="Invalid SDK version")
            print_result(value, args.json)
            return 2
        manager_args.extend(["--sdk-version", args.sdk_version])
    if args.version:
        manager_args.extend(["--version", args.version])
    if args.sdk_action == "project-resolve":
        manager_args.append("--dry-run")
    elif not args.confirm:
        value = result(False, operation, 3, project_id=safe_project_id(args.project), workspace=str(workspace), requires_human_confirm=True, first_failure="SDK pull writes archives and extracted files; rerun with --confirm")
        print_result(value, args.json)
        return 3
    backend = run_sdk_manager(args, manager_args, cwd=workspace)
    value = result(
        bool(backend["ok"]),
        operation,
        int(backend["exit_code"]),
        project_id=background["project_id"] if background else safe_project_id(args.project),
        background_id=background.get("background_id") if background else None,
        workspace=str(workspace),
        dry_run=args.sdk_action == "project-resolve",
        gate={"level": "L2", "requires_human_confirm": True, "confirmed": True} if args.sdk_action == "project-pull" else {"level": "L0", "confirmed": False},
        backend=backend,
    )
    if background:
        append_run(paths, background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])
