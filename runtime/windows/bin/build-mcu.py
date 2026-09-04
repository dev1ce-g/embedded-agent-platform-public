#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from agent_backend_common import *


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Workspace")
    parser.add_argument("-Project")
    parser.add_argument("-ArtifactRoot")
    parser.add_argument("-Uv4Path", default=os.environ.get("AGENTCTL_UV4_PATH"))
    parser.add_argument("-Target", default="application")
    parser.add_argument("-ArtifactName")
    parser.add_argument("-OutputDirectory")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "build-mcu"
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
        return emit(failure(operation, 2, f"MDK project not found: {project}", log=str(log), workspace=str(workspace)), args.Json)

    uv4_log = mdk / "agentctl_mcu_uv4_build.log"
    uv4_log.unlink(missing_ok=True)
    exit_code, stdout, stderr = run_logged(
        [str(uv4), "-b", str(project), "-t", args.Target, "-j0", "-o", str(uv4_log)],
        log,
        cwd=mdk,
    )
    if uv4_log.is_file():
        write_log(log, uv4_log.read_bytes())
    elif not stdout and not stderr:
        write_log(log, f"UV4 log missing: {uv4_log}")
    if args.ArtifactRoot:
        artifact = latest_artifact([Path(args.ArtifactRoot)], ("*.axf", "*.bin", "*.hex"))
    else:
        artifact_name = args.ArtifactName or args.Target
        output_parts = [
            item
            for item in re.split(r"[\\/]+", args.OutputDirectory or "Objects")
            if item not in {"", "."}
        ]
        artifact = file_info(mdk.joinpath(*output_parts, f"{artifact_name}.axf"))
    success_marker = first_match(log, (r"0 Error\(s\)", r"Build complete"))
    failure_marker = first_match(log, (r"Error:", r"failed", r"Undefined symbol"))
    ok = exit_code == 0 and bool(success_marker)
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
            success_marker=success_marker,
            first_failure=failure_marker or (None if ok else "Missing Keil build success marker"),
            artifact=artifact,
        ),
        args.Json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
