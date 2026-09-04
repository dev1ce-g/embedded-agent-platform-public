"""Internal embedded runtime knowledge module."""

from __future__ import annotations

from embedded_runtime_common import *

def compare_background_fingerprints(background: dict[str, Any]) -> dict[str, Any]:
    current = discover_background(background["project_id"], Path(background["workspace"]))
    old = {item["path"]: item["sha256"] for item in background.get("fingerprints", [])}
    new = {item["path"]: item["sha256"] for item in current.get("fingerprints", [])}
    changed = sorted(path for path, digest in new.items() if old.get(path) != digest)
    missing = sorted(path for path in old if path not in new)
    return {
        "stale": bool(changed or missing),
        "changed": changed[:50],
        "missing": missing[:50],
    }

def build_knowledge(paths: AgentPaths, background: dict[str, Any]) -> dict[str, Any]:
    project_id = background["project_id"]
    runs = read_runs(paths, project_id)
    latest_build = latest_run(runs, "build")
    latest_build_ok = latest_run(runs, "build", True)
    latest_flash = latest_run(runs, "flash")
    latest_flash_ok = latest_run(runs, "flash", True)
    latest_rtt = latest_run(runs, "rtt-capture")
    latest_rtt_ok = latest_run(runs, "rtt-capture", True)
    latest_rtt_fail = latest_run(runs, "rtt-capture", False)

    chips = background.get("toolchains", {}).get("chips") or []
    mcu_target = background.get("targets", {}).get("mcu", {})
    selected_keil_path = mcu_target.get("build", {}).get("project")
    keil = next(
        (
            item
            for item in background.get("toolchains", {}).get("keil_projects", [])
            if item.get("path") == selected_keil_path
        ),
        {},
    )
    build_backend = backend_of(latest_build_ok or latest_build)
    flash_backend = backend_of(latest_flash_ok or latest_flash)
    rtt_backend = backend_of(latest_rtt_ok or latest_rtt)
    rtt_fail_backend = backend_of(latest_rtt_fail)

    build_artifact = build_backend.get("artifact")
    flash_artifact = flash_backend.get("artifact")
    rtt_info = rtt_backend.get("rtt") if isinstance(rtt_backend.get("rtt"), dict) else {}
    rtt_capture = rtt_backend.get("capture") if isinstance(rtt_backend.get("capture"), dict) else {}
    flash_markers = flash_backend.get("success_markers") if isinstance(flash_backend.get("success_markers"), dict) else {}

    project_profile = {
        "schema_version": "embedded-project-profile/v1",
        "project_id": project_id,
        "background_id": background.get("background_id"),
        "generated_at": now_iso(),
        "workspace": background.get("workspace"),
        "architecture": background.get("architecture"),
        "repos": background.get("repos", []),
        "targets": background.get("targets", {}),
        "toolchains": background.get("toolchains", {}),
    }

    device_profile = {
        "schema_version": "embedded-device-profile/v1",
        "project_id": project_id,
        "generated_at": now_iso(),
        "mcu": {
            "chip": chips[0] if chips else None,
            "device": keil.get("device"),
            "core": keil.get("device", "").split(":", 1)[1] if ":" in keil.get("device", "") else None,
            "build_method": mcu_target.get("build", {}).get("method"),
            "keil_project": mcu_target.get("build", {}).get("project"),
            "flash_method": "Keil UV4 -f" if flash_backend.get("ok") else None,
            "debug_probe": "J-Link" if rtt_backend.get("tools", {}).get("jlink") else None,
            "rtt": {
                "symbol": "_SEGGER_RTT",
                "symbol_source": rtt_info.get("symbol_source"),
                "symbol_path": rtt_info.get("symbol_path"),
                "symbol_line": rtt_info.get("symbol_line"),
                "address": rtt_info.get("rtt_address"),
                "buffer_address": rtt_info.get("buffer_address"),
                "buffer_size": rtt_info.get("buffer_size"),
            },
        },
    }

    capability_profile = {
        "schema_version": "embedded-capability-profile/v1",
        "project_id": project_id,
        "generated_at": now_iso(),
        "capabilities": {
            "project_discovery": {"status": "ready", "background_id": background.get("background_id")},
            "build_mcu": {
                "status": "ready" if latest_build_ok else "unknown",
                "last_ok": bool(latest_build_ok and latest_build_ok.get("ok")),
                "log": build_backend.get("log"),
                "artifact": build_artifact,
                "success_marker": build_backend.get("success_marker"),
                "first_failure": build_backend.get("first_failure") or (latest_build or {}).get("first_failure"),
            },
            "flash_mcu": {
                "status": "ready" if latest_flash_ok else "gated",
                "gate": "L3",
                "requires_confirm": True,
                "last_ok": bool(latest_flash_ok and latest_flash_ok.get("ok")),
                "log": flash_backend.get("log"),
                "artifact": flash_artifact,
                "success_markers": flash_markers,
                "first_failure": flash_backend.get("first_failure") or (latest_flash or {}).get("first_failure"),
            },
            "rtt_capture": {
                "status": "ready" if latest_rtt_ok else "partial",
                "default_mode": "attach",
                "last_ok": bool(latest_rtt_ok and latest_rtt_ok.get("ok")),
                "last_mode": (latest_rtt_ok or latest_rtt or {}).get("gate", {}).get("mode"),
                "text_log": rtt_backend.get("text_log"),
                "line_count": rtt_capture.get("line_count"),
                "first_failure": rtt_fail_backend.get("first_failure") or (latest_rtt_fail or {}).get("first_failure"),
            },
            "hardfault": {
                "status": "candidate" if latest_rtt_fail else "unknown",
                "evidence": {
                    "source": "rtt attach failure" if latest_rtt_fail else None,
                    "first_failure": rtt_fail_backend.get("first_failure") or (latest_rtt_fail or {}).get("first_failure"),
                    "jlink_log": rtt_fail_backend.get("jlink_log"),
                },
            },
        },
    }

    operation_profile = {
        "schema_version": "embedded-operation-profile/v1",
        "project_id": project_id,
        "generated_at": now_iso(),
        "runs_count": len(runs),
        "latest": {
            "build": latest_build,
            "flash": latest_flash,
            "rtt_capture": latest_rtt,
        },
    }

    evidence_index = {
        "schema_version": "embedded-evidence-index/v1",
        "project_id": project_id,
        "generated_at": now_iso(),
        "latest_build": {
            "ok": (latest_build or {}).get("ok"),
            "log": build_backend.get("log"),
            "artifact": build_artifact,
            "first_failure": build_backend.get("first_failure") or (latest_build or {}).get("first_failure"),
        },
        "latest_flash": {
            "ok": (latest_flash or {}).get("ok"),
            "log": flash_backend.get("log"),
            "artifact": flash_artifact,
            "success_markers": flash_markers,
            "first_failure": flash_backend.get("first_failure") or (latest_flash or {}).get("first_failure"),
        },
        "latest_rtt": {
            "ok": (latest_rtt or {}).get("ok"),
            "mode": (latest_rtt or {}).get("gate", {}).get("mode"),
            "text_log": rtt_backend.get("text_log"),
            "artifact_dir": rtt_backend.get("artifact_dir"),
            "rtt": rtt_info,
            "capture": rtt_capture,
            "first_failure": rtt_backend.get("first_failure") or (latest_rtt or {}).get("first_failure"),
        },
        "known_failures": summarize_known_failures(latest_rtt_fail),
    }

    markdown = render_knowledge_markdown(
        background,
        project_profile,
        device_profile,
        capability_profile,
        evidence_index,
    )
    return {
        "profiles": {
            "project-profile.json": project_profile,
            "device-profile.json": device_profile,
            "capability-profile.json": capability_profile,
            "operation-profile.json": operation_profile,
            "evidence-index.json": evidence_index,
        },
        "markdown": markdown,
        "summary": {
            "project_id": project_id,
            "knowledge_files": 10,
            "build_mcu": capability_profile["capabilities"]["build_mcu"]["status"],
            "flash_mcu": capability_profile["capabilities"]["flash_mcu"]["status"],
            "rtt_capture": capability_profile["capabilities"]["rtt_capture"]["status"],
            "hardfault": capability_profile["capabilities"]["hardfault"]["status"],
        },
    }

def summarize_known_failures(latest_rtt_fail: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not latest_rtt_fail:
        return []
    backend = backend_of(latest_rtt_fail)
    failure = backend.get("first_failure") or latest_rtt_fail.get("first_failure")
    item = {
        "operation": latest_rtt_fail.get("operation"),
        "timestamp": latest_rtt_fail.get("timestamp"),
        "first_failure": failure,
        "log": backend.get("log"),
        "jlink_log": backend.get("jlink_log"),
    }
    if failure and "magic" in str(failure).lower():
        item["hint"] = "RTT control block invalid; check whether target is in HardFault, reset state, or RTT was initialized."
    return [item]

def render_knowledge_markdown(
    background: dict[str, Any],
    project_profile: dict[str, Any],
    device_profile: dict[str, Any],
    capability_profile: dict[str, Any],
    evidence_index: dict[str, Any],
) -> dict[str, str]:
    project_id = background["project_id"]
    mcu = device_profile.get("mcu", {})
    caps = capability_profile["capabilities"]
    latest_build = evidence_index["latest_build"]
    latest_flash = evidence_index["latest_flash"]
    latest_rtt = evidence_index["latest_rtt"]
    known_failures = evidence_index.get("known_failures", [])

    overview = f"""# {project_id} Overview

- Project id: `{project_id}`
- Background id: `{background.get('background_id')}`
- Workspace: `{background.get('workspace')}`
- Architecture: `{background.get('architecture')}`
- MCU: `{mcu.get('device') or mcu.get('chip') or 'unknown'}`
- Keil project: `{mcu.get('keil_project') or 'unknown'}`

This knowledge was generated by the Windows local `embedded-agent` from
canonical project background and operation evidence.
"""

    build = f"""# Build Guide

Use:

```text
embedded-agent build --project {project_id} --target keil --json
```

- Status: `{caps['build_mcu'].get('status')}`
- Last OK: `{caps['build_mcu'].get('last_ok')}`
- Log: `{latest_build.get('log')}`
- Artifact: `{(latest_build.get('artifact') or {}).get('path')}`
- SHA256: `{(latest_build.get('artifact') or {}).get('sha256')}`
- Success marker: `{caps['build_mcu'].get('success_marker')}`
"""

    markers = latest_flash.get("success_markers") or {}
    flash = f"""# Flash Guide

Flash is an L3 gated operation. Use:

```text
embedded-agent flash --project {project_id} --target mcu --require-confirm --confirm --json
```

Required success markers:

- `Erase Done.`
- `Programming Done.`
- `Verify OK.`

Latest evidence:

- Status: `{caps['flash_mcu'].get('status')}`
- Last OK: `{caps['flash_mcu'].get('last_ok')}`
- Log: `{latest_flash.get('log')}`
- Artifact: `{(latest_flash.get('artifact') or {}).get('path')}`
- SHA256: `{(latest_flash.get('artifact') or {}).get('sha256')}`
- Erase marker: `{markers.get('erase')}`
- Programming marker: `{markers.get('programming')}`
- Verify marker: `{markers.get('verify')}`
"""

    rtt = latest_rtt.get("rtt") or {}
    capture = latest_rtt.get("capture") or {}
    rtt_md = f"""# RTT Guide

Default capture uses attach mode and does not reset the target:

```text
embedded-agent rtt capture --project {project_id} --target mcu --wait-ms 12000 --json
```

Use `--reset` only when boot-window logs are needed or attach mode cannot
capture initialized RTT state.

Latest RTT evidence:

- Status: `{caps['rtt_capture'].get('status')}`
- Last OK: `{caps['rtt_capture'].get('last_ok')}`
- Mode: `{latest_rtt.get('mode')}`
- Text log: `{latest_rtt.get('text_log')}`
- Symbol source: `{rtt.get('symbol_source')}`
- RTT address: `{rtt.get('rtt_address')}`
- Buffer: `{rtt.get('buffer_address')}` size `{rtt.get('buffer_size')}`
- Line count: `{capture.get('line_count')}`
"""

    failure_lines = ["# Known Failures", ""]
    if not known_failures:
        failure_lines.append("No known failures recorded yet.")
    for failure in known_failures:
        failure_lines.extend([
            f"- Operation: `{failure.get('operation')}`",
            f"- Timestamp: `{failure.get('timestamp')}`",
            f"- Failure: `{failure.get('first_failure')}`",
            f"- Log: `{failure.get('log')}`",
            f"- J-Link log: `{failure.get('jlink_log')}`",
            f"- Hint: {failure.get('hint', 'n/a')}",
            "",
        ])

    return {
        "overview.md": overview,
        "build-guide.md": build,
        "flash-guide.md": flash,
        "rtt-guide.md": rtt_md,
        "known-failures.md": "\n".join(failure_lines),
    }

def write_knowledge(paths: AgentPaths, project: str, knowledge: dict[str, Any]) -> dict[str, str]:
    kdir = knowledge_dir(paths, project)
    kdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, value in knowledge["profiles"].items():
        path = kdir / name
        write_json(path, value)
        written[name] = str(path)
    for name, content in knowledge["markdown"].items():
        path = kdir / name
        write_text(path, content)
        written[name] = str(path)
    return written

def read_knowledge_summary(paths: AgentPaths, project: str) -> dict[str, Any] | None:
    kdir = knowledge_dir(paths, project)
    evidence_path = kdir / "evidence-index.json"
    capability_path = kdir / "capability-profile.json"
    project_path = kdir / "project-profile.json"
    if not evidence_path.exists() or not capability_path.exists() or not project_path.exists():
        return None
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        capability = json.loads(capability_path.read_text(encoding="utf-8"))
        project_profile = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "project_profile": project_profile,
        "capability_profile": capability,
        "evidence_index": evidence,
        "knowledge_dir": str(kdir),
    }

def copy_tree(src: Path, dst: Path) -> list[str]:
    written: list[str] = []
    if not src.exists():
        return written
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        target = dst / path.name
        target.write_bytes(path.read_bytes())
        written.append(str(target))
    return written

def command_status(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    runtime_files = []
    runtime_dir = Path(__file__).resolve().parent
    tracked_runtime_files = [
        runtime_dir / "embedded_agent.py",
        runtime_dir / "jenkins_client.py",
        runtime_dir / "job_runner.py",
        *(runtime_dir / name for name in RUNTIME_MODULE_FILES),
        paths.root.parent / "bin" / "embedded-agent.py",
        Path(args.agentctl).resolve(),
    ]
    for path in tracked_runtime_files:
        runtime_files.append({"path": str(path), "exists": path.is_file(), "sha256": sha256_file(path)})
    value = result(
        True,
        "status",
        root=str(paths.root),
        projects=str(paths.projects),
        jobs=str(paths.jobs),
        agentctl=str(args.agentctl),
        python=sys.version.split()[0],
        runtime_contract_version=RUNTIME_CONTRACT_VERSION,
        runtime_files=runtime_files,
    )
    print_result(value, args.json)
    return 0

def command_project(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    if args.project_action == "discover":
        if not args.workspace:
            value = result(False, "project-discover", 2, first_failure="Missing --workspace")
            print_result(value, args.json)
            return 2
        selected_keil_project = args.mcu_keil_project
        selection_source = "explicit" if selected_keil_project else None
        if not selected_keil_project:
            existing = read_background(paths, args.project)
            existing_workspace = str((existing or {}).get("workspace", "")).replace("\\", "/").lower()
            requested_workspace = str(Path(args.workspace).resolve()).replace("\\", "/").lower()
            if existing_workspace == requested_workspace:
                existing_build = (existing or {}).get("targets", {}).get("mcu", {}).get("build", {})
                if existing_build.get("selection_source") in {"explicit", "existing_background"}:
                    selected_keil_project = existing_build.get("project")
                if selected_keil_project:
                    selection_source = "existing_background"
        background = discover_background(
            args.project,
            Path(args.workspace),
            mcu_keil_project=selected_keil_project,
            selection_source=selection_source,
        )
        mcu_build = background.get("targets", {}).get("mcu", {}).get("build", {})
        selection_status = mcu_build.get("selection_status")
        candidates = [
            {
                "path": item.get("path"),
                "target": item.get("target"),
                "device": item.get("device"),
                "output": item.get("output"),
                "output_kind": item.get("output_kind"),
            }
            for item in background.get("toolchains", {}).get("keil_projects", [])
        ]
        selection_blocked = selection_status in {"selection_required", "invalid_selection", "invalid_kind"}
        if args.write_background and selection_blocked:
            value = result(
                False,
                "project-discover",
                5,
                project_id=background["project_id"],
                workspace=background["workspace"],
                blocked=True,
                gate="keil-project-selection",
                requires_user_selection=True,
                selection_status=selection_status,
                selection_candidates=candidates,
                next_hint=(
                    "Ask the user to select one Keil project, then rerun project discover "
                    "with --keil-project <workspace-relative-path> --write-background"
                ),
                first_failure="Keil project selection is required before writing project background",
            )
            print_result(value, args.json)
            return 5
        value = result(
            True,
            "project-discover",
            project_id=background["project_id"],
            background_id=background["background_id"],
            architecture=background["architecture"],
            workspace=background["workspace"],
            capabilities=background["capabilities"],
            requires_user_selection=selection_status == "selection_required",
            selection_status=selection_status,
            selection_candidates=candidates,
        )
        if args.write_background:
            json_path, md_path = write_background(paths, background)
            value["background_json"] = str(json_path)
            value["background_md"] = str(md_path)
        else:
            value["background"] = background
        print_result(value, args.json)
        return 0

    background = read_background(paths, args.project)
    if not background:
        value = result(
            False,
            f"project-{args.project_action}",
            2,
            project_id=safe_project_id(args.project),
            first_failure="Project background not found",
            next_hint="Run project discover --write-background first",
        )
        print_result(value, args.json)
        return 2

    if args.project_action == "show":
        print_result(result(True, "project-show", background=background), args.json)
        return 0

    if args.project_action == "check-stale":
        stale_info = compare_background_fingerprints(background)
        print_result(
            result(
                True,
                "project-check-stale",
                project_id=background["project_id"],
                background_id=background["background_id"],
                **stale_info,
            ),
            args.json,
        )
        return 0

    print_result(result(False, "project", 2, first_failure=f"Unknown action: {args.project_action}"), args.json)
    return 2

def command_knowledge(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(False, f"knowledge-{args.knowledge_action}", 2, project_id=safe_project_id(args.project), first_failure="Project background not found")
        print_result(value, args.json)
        return 2

    if args.knowledge_action == "build":
        knowledge = build_knowledge(paths, background)
        written = write_knowledge(paths, background["project_id"], knowledge) if args.write else {}
        value = result(
            True,
            "knowledge-build",
            project_id=background["project_id"],
            background_id=background["background_id"],
            knowledge_dir=str(knowledge_dir(paths, background["project_id"])),
            summary=knowledge["summary"],
            written=written,
        )
        if not args.write:
            value["knowledge"] = knowledge
        print_result(value, args.json)
        return 0

    if args.knowledge_action == "show":
        summary = read_knowledge_summary(paths, background["project_id"])
        if not summary:
            value = result(False, "knowledge-show", 2, project_id=background["project_id"], first_failure="Knowledge not found; run knowledge build --write first")
            print_result(value, args.json)
            return 2
        print_result(result(True, "knowledge-show", project_id=background["project_id"], **summary), args.json)
        return 0

    if args.knowledge_action == "export":
        summary = read_knowledge_summary(paths, background["project_id"])
        if not summary:
            value = result(False, "knowledge-export", 2, project_id=background["project_id"], first_failure="Knowledge not found; run knowledge build --write first")
            print_result(value, args.json)
            return 2
        target = Path(args.to).expanduser()
        written = copy_tree(knowledge_dir(paths, background["project_id"]), target)
        print_result(
            result(
                True,
                "knowledge-export",
                project_id=background["project_id"],
                source=str(knowledge_dir(paths, background["project_id"])),
                target=str(target),
                written=written,
            ),
            args.json,
        )
        return 0

    print_result(result(False, "knowledge", 2, first_failure=f"Unknown action: {args.knowledge_action}"), args.json)
    return 2
