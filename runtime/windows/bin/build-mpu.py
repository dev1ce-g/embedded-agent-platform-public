#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path

from agent_backend_common import *


def docker_capture(arguments: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        completed = subprocess.run(["docker", *arguments], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode("utf-8", errors="replace")
    except OSError as exc:
        return 127, str(exc)
    return completed.returncode, (completed.stdout or b"").decode("utf-8", errors="replace").strip()


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    replace_config = not args.SkipTargetConfig and bool(args.TargetConfigSource) and bool(args.TargetConfigDir)
    lines = ["set -euo pipefail"]
    if replace_config:
        lines.extend([f"cd {shlex.quote(args.TargetConfigDir)}", "rm -rf target.config", f"cp {shlex.quote(args.TargetConfigSource)} ./target.config"])
    lines.extend(
        [
            f"cd {shlex.quote(args.DockerWorkdir)}",
            f"export ql_sdk_path={shlex.quote(args.QlSdkPath)}",
            f"export new_build={'1' if args.Mode == 'full' else '0'}",
            "export build_bin=1",
            "./build_new_sdk.sh",
        ]
    )
    return {
        "workspace": args.Workspace,
        "artifact_root": args.ArtifactRoot,
        "container": args.Container,
        "mode": args.Mode,
        "docker_workdir": args.DockerWorkdir,
        "ql_sdk_path": args.QlSdkPath,
        "container_artifact_path": args.ContainerArtifactPath,
        "new_build": "1" if args.Mode == "full" else "0",
        "build_bin": "1",
        "target_config": {
            "enabled": replace_config,
            "required": args.RequireTargetConfig,
            "skipped": args.SkipTargetConfig,
            "source": args.TargetConfigSource,
            "destination_dir": args.TargetConfigDir,
        },
        "inner": "; ".join(lines),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Workspace")
    parser.add_argument("-ArtifactRoot")
    parser.add_argument("-Container", default=os.environ.get("AGENTCTL_MPU_CONTAINER", "embedded-build"))
    parser.add_argument("-Mode", choices=("incremental", "full"), default="incremental")
    parser.add_argument("-DockerWorkdir", default=os.environ.get("AGENTCTL_MPU_WORKDIR", "/home/project/mpu/project/cmake"))
    parser.add_argument("-QlSdkPath", default=os.environ.get("AGENTCTL_MPU_SDK_PATH", "/home/ql-sdk"))
    parser.add_argument("-ContainerArtifactPath", default=os.environ.get("AGENTCTL_MPU_ARTIFACT_PATH", "/home/build/target"))
    parser.add_argument("-TargetConfigSource")
    parser.add_argument("-TargetConfigDir")
    parser.add_argument("-SkipTargetConfig", action="store_true")
    parser.add_argument("-RequireTargetConfig", action="store_true")
    parser.add_argument("-DryRun", action="store_true")
    parser.add_argument("-Json", action="store_true")
    args = parser.parse_args(argv)
    operation = "build-mpu"
    started = now_iso()
    log = new_log_path(operation)
    plan = build_plan(args)
    if bool(args.TargetConfigSource) != bool(args.TargetConfigDir):
        return emit(failure(operation, 2, "target.config replacement requires both --target-config-source and --target-config-dir", log=str(log), workspace=args.Workspace, plan=plan), args.Json)
    if args.RequireTargetConfig and not args.SkipTargetConfig and not (args.TargetConfigSource and args.TargetConfigDir):
        return emit(failure(operation, 2, "target.config replacement is required but not configured", log=str(log), workspace=args.Workspace, plan=plan), args.Json)
    workspace = Path(args.Workspace) if args.Workspace else None
    if workspace is None or not workspace.is_dir():
        return emit(failure(operation, 2, "Workspace not found", log=str(log), workspace=args.Workspace, plan=plan), args.Json)
    if shutil.which("docker") is None:
        return emit(failure(operation, 127, "docker command not found", log=str(log), workspace=str(workspace), plan=plan), args.Json)
    if args.DryRun:
        return emit(result(True, operation, workspace=str(workspace), container=args.Container, mode=args.Mode, dry_run=True, started_at=started, ended_at=now_iso(), log=str(log), plan=plan), args.Json)

    container = args.Container
    code, state = docker_capture(["container", "inspect", "--format", "{{.State.Running}}", container])
    if code != 0:
        return emit(failure(operation, code, f"Docker container is unavailable: {container}", log=str(log), workspace=str(workspace), container=container, plan=plan), args.Json)
    container_started = False
    container_created = False
    if state.strip().lower() != "true":
        code, output = docker_capture(["start", container])
        if code != 0:
            return emit(failure(operation, code, f"Failed to start Docker container: {container}", log=str(log), workspace=str(workspace), container=container, plan=plan, backend_output=output), args.Json)
        container_started = True

    _, image = docker_capture(["container", "inspect", "--format", "{{.Config.Image}}", container])
    _, mounts = docker_capture(["container", "inspect", "--format", "{{range .Mounts}}{{println .Type \"|\" .Source \"|\" .Name \"|\" .Destination \"|\" .RW}}{{end}}", container])
    plan["container_image"] = image
    plan["container_mounts"] = mounts.splitlines()
    host_script = workspace / "mpu" / "project" / "cmake" / "build_new_sdk.sh"
    host_info = file_info(host_script)
    if host_info is None:
        return emit(failure(operation, 2, "Controlled MPU build script not found", log=str(log), workspace=str(workspace), container=container, plan=plan), args.Json)
    container_script = f"{args.DockerWorkdir}/build_new_sdk.sh"
    probe = ["exec", container, "bash", "-lc", f"sha256sum {shlex.quote(container_script)}"]
    probe_code, probe_output = docker_capture(probe)
    match = re.search(r"(?im)^\s*([0-9a-f]{64})\s+", probe_output)
    container_hash = match.group(1).lower() if match else None
    plan.update(host_build_script_sha256=host_info["sha256"], container_build_script_sha256=container_hash, container_build_script_probe=probe_output)

    if probe_code != 0 or container_hash != host_info["sha256"]:
        label = re.sub(r"[^A-Za-z0-9_.-]", "-", workspace.parent.name) or host_info["sha256"][:12]
        isolated = f"{container}-{label}"
        inspect_code, isolated_state = docker_capture(["container", "inspect", "--format", "{{.State.Running}}", isolated])
        if inspect_code == 0:
            if isolated_state.strip().lower() != "true":
                code, output = docker_capture(["start", isolated])
                if code != 0:
                    return emit(failure(operation, code, "Failed to start isolated MPU Docker container", log=str(log), workspace=str(workspace), container=isolated, plan=plan, backend_output=output), args.Json)
                container_started = True
        else:
            if not image:
                return emit(failure(operation, 5, "Docker source image is unavailable", log=str(log), workspace=str(workspace), container=container, plan=plan), args.Json)
            mount = f"type=bind,source={workspace},target=/home/project"
            code, output = docker_capture(["run", "-d", "--name", isolated, "--mount", mount, image, "tail", "-f", "/dev/null"])
            if code != 0:
                return emit(failure(operation, code, "Failed to create isolated MPU Docker container", log=str(log), workspace=str(workspace), container=isolated, plan=plan, backend_output=output), args.Json)
            container_started = True
            container_created = True
        plan.update(requested_container=container, container=isolated, isolated_workspace_container=True, container_created=container_created)
        container = isolated
        probe_code, probe_output = docker_capture(["exec", container, "bash", "-lc", f"sha256sum {shlex.quote(container_script)}"])
        match = re.search(r"(?im)^\s*([0-9a-f]{64})\s+", probe_output)
        container_hash = match.group(1).lower() if match else None
        plan.update(container_build_script_sha256=container_hash, container_build_script_probe=probe_output)
    if probe_code != 0 or container_hash != host_info["sha256"]:
        return emit(failure(operation, 5, "Docker container does not expose the controlled MPU workspace", log=str(log), workspace=str(workspace), container=container, plan=plan), args.Json)

    exit_code, stdout, stderr = run_logged(["docker", "exec", container, "bash", "-lc", plan["inner"]], log)
    artifact = None
    export_value = None
    if exit_code == 0:
        base = Path(args.ArtifactRoot) if args.ArtifactRoot else workspace / "_codex_builds" / "mpu-docker-artifacts"
        destination = base / datetime.now().strftime("%Y%m%d-%H%M%S")
        destination.mkdir(parents=True, exist_ok=True)
        source = f"{container}:{args.ContainerArtifactPath}"
        export_code, export_output = docker_capture(["cp", source, str(destination)], timeout=300)
        export_value = {"source": source, "destination": str(destination), "exit_code": export_code, "output": export_output}
        if export_code != 0:
            exit_code = max(1, export_code)
        else:
            artifact = latest_artifact([destination], ("*.pac", "*.bin", "*.zip"))
            if artifact is None:
                exit_code = 1
    success_marker = first_match(log, (r"build ended successfully", r"build complete"))
    first_failure = first_match(log, (r"error:", r"failed", r"undefined reference"))
    if exit_code != 0 and not first_failure:
        first_failure = "Failed to export MPU Docker artifact" if export_value and export_value["exit_code"] else "No packaged MPU artifact was exported from the Docker container"
    ok = exit_code == 0 and bool(success_marker) and artifact is not None
    if not ok and exit_code == 0:
        exit_code = 1
    return emit(result(ok, operation, exit_code, workspace=str(workspace), container=container, container_started=container_started, container_created=container_created, mode=args.Mode, started_at=started, ended_at=now_iso(), log=str(log), plan=plan, success_marker=success_marker, first_failure=first_failure, artifact=artifact, artifact_export=export_value), args.Json)


if __name__ == "__main__":
    raise SystemExit(main())
