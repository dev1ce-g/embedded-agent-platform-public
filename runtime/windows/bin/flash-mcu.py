#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from agent_backend_common import *


def marker(path: Path, label: str, patterns: tuple[str, ...]) -> str | None:
    return label if first_match(path, patterns) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Workspace")
    parser.add_argument("-Project")
    parser.add_argument("-Uv4Path", default=os.environ.get("AGENTCTL_UV4_PATH"))
    parser.add_argument("-Target", default="application")
    parser.add_argument("-ArtifactName")
    parser.add_argument("-OutputDirectory")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "flash-mcu"
    started = now_iso()
    log = new_log_path(operation)
    workspace = Path(args.Workspace) if args.Workspace else None
    if workspace is None or not workspace.is_dir():
        return emit(failure(operation, 2, "Workspace not found", log=str(log), workspace=args.Workspace), args.Json)
    uv4 = Path(args.Uv4Path) if args.Uv4Path else None
    if not args.Project:
        value = failure(operation, 2, "Keil project path is required", log=str(log), workspace=str(workspace))
        return emit(value, args.Json)
    project = (workspace / args.Project).resolve()
    try:
        project.relative_to(workspace.resolve())
    except ValueError:
        value = failure(
            operation,
            5,
            "Keil project must be inside the registered workspace",
            log=str(log),
            workspace=str(workspace),
            project=str(project),
        )
        return emit(value, args.Json)
    mdk = project.parent
    if uv4 is None or not uv4.is_file():
        return emit(failure(operation, 127, f"UV4 not found: {uv4}", log=str(log), workspace=str(workspace)), args.Json)
    if not project.is_file() or project.suffix.lower() not in {".uvprojx", ".uvproj"}:
        value = failure(operation, 2, f"MDK project not found: {project}", log=str(log), workspace=str(workspace))
        return emit(value, args.Json)
    artifact_name = args.ArtifactName or args.Target
    output_parts = [
        item
        for item in re.split(r"[\\/]+", args.OutputDirectory or "Objects")
        if item not in {"", "."}
    ]
    artifact_path = mdk.joinpath(*output_parts, f"{artifact_name}.axf")
    artifact = file_info(artifact_path)
    if not artifact:
        value = failure(
            operation,
            6,
            f"Expected flash artifact not found: {artifact_path}",
            log=str(log),
            workspace=str(workspace),
            project=str(project),
        )
        return emit(value, args.Json)

    preflight = {
        "gate_level": "L3",
        "workspace": str(workspace),
        "uv4": str(uv4),
        "project": str(project),
        "target": args.Target,
        "artifact": artifact,
        "checks": {"workspace_exists": True, "uv4_exists": True, "project_exists": True, "artifact_exists": True},
    }
    uv4_log = mdk / "agentctl_mcu_uv4_flash.log"
    uv4_log.unlink(missing_ok=True)
    exit_code, stdout, stderr = run_logged(
        [str(uv4), "-f", str(project), "-t", args.Target, "-j0", "-o", str(uv4_log)],
        log,
        cwd=mdk,
    )
    if uv4_log.is_file():
        write_log(log, uv4_log.read_bytes())
    elif not stdout and not stderr:
        write_log(log, f"UV4 log missing: {uv4_log}")
    markers = {
        "erase": marker(log, "Erase Done.", (r"Erase Done\.?",)),
        "programming": marker(log, "Programming Done.", (r"Programming Done\.?",)),
        "verify": marker(log, "Verify OK.", (r"Verify OK\.?",)),
        "reset_run": marker(log, "Application running", (r"Application running", r"Reset device via")),
    }
    first_failure = first_match(log, (r"Error:", r"failed", r"No ULINK", r"No J-Link", r"Cannot", r"could not"))
    required_markers = (markers["erase"], markers["programming"], markers["verify"])
    ok = exit_code == 0 and all(required_markers)
    if not ok and not first_failure:
        missing = next((name for name, value in markers.items() if not value), None)
        first_failure = (
            f"Missing success marker: {missing}"
            if missing
            else f"Keil flash process exited with code {exit_code}"
        )
    if not ok and exit_code == 0:
        exit_code = 1
    return emit(
        result(
            ok,
            operation,
            exit_code,
            workspace=str(workspace),
            started_at=started,
            ended_at=now_iso(),
            log=str(log),
            preflight=preflight,
            success_markers=markers,
            first_failure=first_failure,
            artifact=artifact,
        ),
        args.Json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
