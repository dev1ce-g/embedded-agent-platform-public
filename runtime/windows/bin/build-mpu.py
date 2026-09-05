#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath

from agent_backend_common import *


def docker_capture(arguments: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        completed = subprocess.run(["docker", *arguments], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode("utf-8", errors="replace")
    except OSError as exc:
        return 127, str(exc)
    return completed.returncode, (completed.stdout or b"").decode("utf-8", errors="replace").strip()


MPU_WORKDIR_SUFFIX = ("mpu", "project", "cmake")
MPU_ARTIFACT_ROOT = Path("_embedded_builds") / "mpu-docker-artifacts"


def inspect_container(reference: str) -> tuple[int, dict[str, Any] | None, str]:
    """Return one Docker inspect document without trusting formatted text."""
    code, output = docker_capture(["container", "inspect", reference])
    if code != 0:
        return code, None, output
    try:
        documents = json.loads(output)
    except json.JSONDecodeError:
        return 5, None, "Docker inspect did not return valid JSON"
    if not isinstance(documents, list) or len(documents) != 1 or not isinstance(documents[0], dict):
        return 5, None, "Docker inspect did not return exactly one container"
    document = documents[0]
    if not isinstance(document.get("Id"), str) or not document["Id"]:
        return 5, None, "Docker inspect result is missing the container id"
    return 0, document, output


def canonical_host_path(value: Path | str) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def workspace_mount_destination(docker_workdir: str) -> str:
    workdir = PurePosixPath(docker_workdir)
    if (
        not workdir.is_absolute()
        or ".." in workdir.parts
        or tuple(workdir.parts[-len(MPU_WORKDIR_SUFFIX):]) != MPU_WORKDIR_SUFFIX
    ):
        raise ValueError("Docker workdir must end exactly with mpu/project/cmake")
    destination = workdir
    for _ in MPU_WORKDIR_SUFFIX:
        destination = destination.parent
    if str(destination) == "/":
        raise ValueError("Docker workspace mount destination is too broad")
    return str(destination)


def validated_artifact_path(value: str) -> str:
    artifact_path = PurePosixPath(value)
    meaningful_parts = [part for part in artifact_path.parts if part != "/"]
    if (
        not artifact_path.is_absolute()
        or ".." in artifact_path.parts
        or len(meaningful_parts) < 2
    ):
        raise ValueError("Container artifact path must be a scoped absolute path")
    return str(artifact_path)


def fixed_mpu_artifact_root(workspace: Path, configured: str | None) -> Path:
    expected = validated_workspace_output_path(
        workspace,
        MPU_ARTIFACT_ROOT,
        label="MPU artifact output",
    )
    if configured:
        requested = Path(configured).expanduser()
        if not requested.is_absolute():
            requested = workspace / requested
        requested = Path(os.path.abspath(os.fspath(requested)))
        if os.path.normcase(str(requested)) != os.path.normcase(str(expected)):
            raise ValueError(f"MPU artifact root is fixed to the registered workspace: {expected}")
    if expected.exists() and not expected.is_dir():
        raise ValueError(f"MPU artifact output is not a directory: {expected}")
    return expected


def validate_workspace_mount(
    document: dict[str, Any],
    workspace: Path,
    docker_workdir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Require the exact current workspace as a writable Docker bind mount."""
    expected_source = canonical_host_path(workspace)
    try:
        expected_destination = workspace_mount_destination(docker_workdir)
    except ValueError as exc:
        return None, str(exc)
    mounts = document.get("Mounts")
    if not isinstance(mounts, list):
        return None, "Docker inspect result has no mount list"
    for mount in mounts:
        if not isinstance(mount, dict) or mount.get("Type") != "bind":
            continue
        source = mount.get("Source")
        if not isinstance(source, str):
            continue
        try:
            actual_source = canonical_host_path(source)
        except OSError:
            continue
        if actual_source != expected_source:
            continue
        if mount.get("Destination") != expected_destination:
            return None, "Docker workspace bind mount destination does not match DockerWorkdir"
        if mount.get("RW") is not True:
            return None, "Docker workspace bind mount is not writable"
        return mount, None
    return None, "Docker container is not bound to the current canonical workspace"


def _is_docker_socket_reference(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.replace("\\", "/").rstrip("/").casefold()
    return normalized.endswith("/docker.sock") or normalized in {
        "docker.sock",
        "//./pipe/docker_engine",
    }


def _container_paths_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_container_isolation(
    document: dict[str, Any],
    workspace_mount: dict[str, Any] | None,
    artifact_path: str,
) -> str | None:
    """Validate an inspected builder before it can execute project code.

    The exact workspace bind is the only permitted writable mount. Read-only
    toolchain inputs remain supported, except for Docker's control socket. The
    artifact cleanup path must stay entirely in the container's private layer.
    """
    host_config = document.get("HostConfig")
    if not isinstance(host_config, dict):
        return "Docker inspect result has no HostConfig isolation data"
    if host_config.get("Privileged", False) is not False:
        return "Privileged Docker containers are not permitted"

    for field, label in (
        ("NetworkMode", "network"),
        ("PidMode", "PID"),
        ("IpcMode", "IPC"),
        ("UsernsMode", "user namespace"),
    ):
        mode = host_config.get(field, "")
        if mode is None:
            mode = ""
        if not isinstance(mode, str):
            return f"Docker {label} mode cannot be verified"
        if mode.casefold() == "host":
            return f"Docker host {label} mode is not permitted"

    for field, label in (
        ("Devices", "device mappings"),
        ("DeviceRequests", "device requests"),
        ("CapAdd", "added Linux capabilities"),
    ):
        configured = host_config.get(field)
        if configured is not None and configured != []:
            return f"Docker {label} are not permitted"

    try:
        artifact = PurePosixPath(validated_artifact_path(artifact_path))
    except ValueError as exc:
        return str(exc)
    mounts = document.get("Mounts")
    if not isinstance(mounts, list):
        return "Docker inspect result has no mount list"
    for mount in mounts:
        if not isinstance(mount, dict):
            return "Docker inspect result contains an invalid mount"
        source = mount.get("Source")
        destination_value = mount.get("Destination")
        if _is_docker_socket_reference(source) or _is_docker_socket_reference(destination_value):
            return "Docker socket mounts are not permitted"
        if mount.get("RW") is True:
            if mount is not workspace_mount:
                return "Docker container has a writable mount outside the registered workspace"
        elif mount.get("RW") is not False:
            return "Docker mount access mode cannot be verified"
        if not isinstance(destination_value, str):
            return "Docker mount destination cannot be verified"
        destination = PurePosixPath(destination_value)
        if not destination.is_absolute() or ".." in destination.parts:
            return "Docker mount destination must be an absolute normalized path"
        if _container_paths_overlap(artifact, destination):
            return "Container artifact path overlaps a Docker mount destination"
    return None


def isolated_container_name(container: str, workspace: Path, host_script_sha256: str) -> tuple[str, str]:
    canonical_workspace = canonical_host_path(workspace)
    digest = hashlib.sha256(
        f"{canonical_workspace}\0{host_script_sha256}".encode("utf-8")
    ).hexdigest()
    label = re.sub(r"[^A-Za-z0-9_.-]", "-", container).strip(".-")
    if not label or not label[0].isalnum():
        label = "embedded-build"
    return f"{label[:210]}-ctx-{digest[:32]}", digest


def container_mounts_for_evidence(document: dict[str, Any]) -> list[dict[str, Any]]:
    mounts = document.get("Mounts")
    if not isinstance(mounts, list):
        return []
    return [
        {
            "type": mount.get("Type"),
            "source": mount.get("Source"),
            "destination": mount.get("Destination"),
            "rw": mount.get("RW"),
        }
        for mount in mounts
        if isinstance(mount, dict)
    ]


def ensure_container_running(
    document: dict[str, Any],
) -> tuple[int, dict[str, Any] | None, bool, str]:
    state = document.get("State")
    if isinstance(state, dict) and state.get("Running") is True:
        return 0, document, False, ""
    reference = str(document["Id"])
    code, output = docker_capture(["start", reference])
    if code != 0:
        return code, None, False, output
    inspect_code, refreshed, inspect_output = inspect_container(reference)
    if inspect_code != 0:
        return inspect_code, None, False, inspect_output
    return 0, refreshed, True, output


def probe_build_script(container_id: str, container_script: str) -> tuple[int, str, str | None]:
    code, output = docker_capture(
        ["exec", container_id, "bash", "-lc", f"sha256sum {shlex.quote(container_script)}"]
    )
    match = re.search(r"(?im)^\s*([0-9a-f]{64})\s+", output)
    return code, output, match.group(1).lower() if match else None


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
    workspace_value = Path(args.Workspace) if args.Workspace else None
    if workspace_value is None or not workspace_value.is_dir():
        return emit(failure(operation, 2, "Workspace not found", log=str(log), workspace=args.Workspace, plan=plan), args.Json)
    workspace = workspace_value.resolve()
    plan["workspace"] = str(workspace)
    try:
        artifact_root = fixed_mpu_artifact_root(workspace_value, args.ArtifactRoot)
    except (OSError, RuntimeError, ValueError) as exc:
        return emit(
            failure(
                operation,
                5,
                str(exc),
                blocked=True,
                log=str(log),
                workspace=str(workspace),
                plan=plan,
            ),
            args.Json,
        )
    plan["artifact_root"] = str(artifact_root)
    try:
        mount_destination = workspace_mount_destination(args.DockerWorkdir)
        artifact_path = validated_artifact_path(args.ContainerArtifactPath)
    except ValueError as exc:
        return emit(failure(operation, 2, str(exc), log=str(log), workspace=str(workspace), plan=plan), args.Json)
    plan["workspace_mount_destination"] = mount_destination
    plan["container_artifact_path"] = artifact_path

    def inspect_context(
        document: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        workspace_mount, workspace_failure = validate_workspace_mount(
            document,
            workspace,
            args.DockerWorkdir,
        )
        isolation_failure = validate_container_isolation(
            document,
            workspace_mount,
            artifact_path,
        )
        return workspace_mount, workspace_failure, isolation_failure

    def block_unsafe_container(container: str, stage: str, reason: str) -> int:
        isolation = {
            "valid": False,
            "stage": stage,
            "container": container,
            "failure": reason,
        }
        plan["container_isolation"] = isolation
        return emit(
            failure(
                operation,
                5,
                reason,
                blocked=True,
                log=str(log),
                workspace=str(workspace),
                container=container,
                container_isolation=isolation,
                plan=plan,
            ),
            args.Json,
        )

    if shutil.which("docker") is None:
        return emit(failure(operation, 127, "docker command not found", log=str(log), workspace=str(workspace), plan=plan), args.Json)
    if args.DryRun:
        return emit(result(True, operation, workspace=str(workspace), container=args.Container, mode=args.Mode, dry_run=True, started_at=started, ended_at=now_iso(), log=str(log), plan=plan), args.Json)

    requested_container = args.Container
    inspect_code, requested_document, inspect_output = inspect_container(requested_container)
    if inspect_code != 0 or requested_document is None:
        return emit(failure(operation, inspect_code, f"Docker container is unavailable: {requested_container}", log=str(log), workspace=str(workspace), container=requested_container, plan=plan, backend_output=inspect_output), args.Json)
    config = requested_document.get("Config")
    image = config.get("Image") if isinstance(config, dict) and isinstance(config.get("Image"), str) else ""
    plan["container_image"] = image
    plan["requested_container_mounts"] = container_mounts_for_evidence(requested_document)
    requested_mount, requested_mount_error, requested_isolation_error = inspect_context(
        requested_document
    )
    plan["requested_container_context"] = {
        "valid": requested_mount is not None and requested_isolation_error is None,
        "workspace_failure": requested_mount_error,
        "isolation_failure": requested_isolation_error,
    }
    if requested_isolation_error:
        return block_unsafe_container(
            requested_container,
            "requested",
            requested_isolation_error,
        )

    host_script = workspace / "mpu" / "project" / "cmake" / "build_new_sdk.sh"
    host_info = file_info(host_script)
    if host_info is None:
        return emit(failure(operation, 2, "Controlled MPU build script not found", log=str(log), workspace=str(workspace), container=requested_container, plan=plan), args.Json)
    container_script = f"{args.DockerWorkdir.rstrip('/')}/build_new_sdk.sh"
    isolated, context_digest = isolated_container_name(requested_container, workspace, host_info["sha256"])
    plan.update(
        host_build_script_sha256=host_info["sha256"],
        workspace_context_digest=context_digest,
        isolated_container=isolated,
    )

    container_started = False
    container_created = False
    selected_name = requested_container
    selected_document: dict[str, Any] | None = None
    if requested_mount is not None:
        code, running_document, started_now, output = ensure_container_running(requested_document)
        if code != 0 or running_document is None:
            return emit(failure(operation, code, f"Failed to start Docker container: {requested_container}", log=str(log), workspace=str(workspace), container=requested_container, plan=plan, backend_output=output), args.Json)
        container_started = container_started or started_now
        running_mount, running_mount_error, running_isolation_error = inspect_context(
            running_document
        )
        if running_isolation_error:
            return block_unsafe_container(
                requested_container,
                "requested-running",
                running_isolation_error,
            )
        if running_mount is None:
            return emit(failure(operation, 5, running_mount_error or "Docker workspace mount validation failed", log=str(log), workspace=str(workspace), container=requested_container, plan=plan), args.Json)
        probe_code, probe_output, container_hash = probe_build_script(
            str(running_document["Id"]),
            container_script,
        )
        plan.update(
            container_build_script_sha256=container_hash,
            container_build_script_probe=probe_output,
        )
        if probe_code == 0 and container_hash == host_info["sha256"]:
            selected_document = running_document
        else:
            plan["isolation_reason"] = "controlled build script hash mismatch"
    else:
        plan["isolation_reason"] = requested_mount_error

    if selected_document is None:
        isolated_inspect_code, isolated_document, isolated_output = inspect_container(isolated)
        if isolated_inspect_code == 0 and isolated_document is not None:
            isolated_mount, isolated_mount_error, isolated_isolation_error = inspect_context(
                isolated_document
            )
            if isolated_isolation_error:
                return block_unsafe_container(
                    isolated,
                    "isolated-existing",
                    isolated_isolation_error,
                )
            if isolated_mount is None:
                return emit(failure(operation, 5, f"Existing isolated MPU container failed workspace mount validation: {isolated_mount_error}", log=str(log), workspace=str(workspace), container=isolated, plan=plan), args.Json)
            code, running_document, started_now, output = ensure_container_running(isolated_document)
            if code != 0 or running_document is None:
                return emit(failure(operation, code, "Failed to start isolated MPU Docker container", log=str(log), workspace=str(workspace), container=isolated, plan=plan, backend_output=output), args.Json)
            container_started = container_started or started_now
            isolated_mount, isolated_mount_error, isolated_isolation_error = inspect_context(
                running_document
            )
            if isolated_isolation_error:
                return block_unsafe_container(
                    isolated,
                    "isolated-running",
                    isolated_isolation_error,
                )
            if isolated_mount is None:
                return emit(failure(operation, 5, f"Existing isolated MPU container failed workspace mount validation: {isolated_mount_error}", log=str(log), workspace=str(workspace), container=isolated, plan=plan), args.Json)
            selected_document = running_document
        else:
            if not image:
                return emit(failure(operation, 5, "Docker source image is unavailable", log=str(log), workspace=str(workspace), container=requested_container, plan=plan), args.Json)
            mount = f"type=bind,source={workspace},target={mount_destination}"
            code, output = docker_capture(["run", "-d", "--name", isolated, "--mount", mount, image, "tail", "-f", "/dev/null"])
            if code != 0:
                return emit(failure(operation, code, "Failed to create isolated MPU Docker container", log=str(log), workspace=str(workspace), container=isolated, plan=plan, backend_output=output), args.Json)
            container_started = True
            container_created = True
            created_inspect_code, created_document, created_output = inspect_container(isolated)
            if created_inspect_code != 0 or created_document is None:
                return emit(failure(operation, created_inspect_code, "Created MPU Docker container cannot be inspected", log=str(log), workspace=str(workspace), container=isolated, plan=plan, backend_output=created_output), args.Json)
            created_mount, created_mount_error, created_isolation_error = inspect_context(
                created_document
            )
            if created_isolation_error:
                return block_unsafe_container(
                    isolated,
                    "isolated-created",
                    created_isolation_error,
                )
            if created_mount is None:
                return emit(failure(operation, 5, f"Created MPU Docker container failed workspace mount validation: {created_mount_error}", log=str(log), workspace=str(workspace), container=isolated, plan=plan), args.Json)
            selected_document = created_document
        selected_name = isolated
        probe_code, probe_output, container_hash = probe_build_script(
            str(selected_document["Id"]),
            container_script,
        )
        plan.update(
            container_build_script_sha256=container_hash,
            container_build_script_probe=probe_output,
        )
        if probe_code != 0 or container_hash != host_info["sha256"]:
            return emit(failure(operation, 5, "Docker container does not expose the controlled MPU workspace", log=str(log), workspace=str(workspace), container=selected_name, plan=plan), args.Json)

    validated_container_id = str(selected_document["Id"])
    validated_mount, mount_error, selected_isolation_error = inspect_context(
        selected_document
    )
    if selected_isolation_error:
        return block_unsafe_container(
            selected_name,
            "selected",
            selected_isolation_error,
        )
    if validated_mount is None:
        return emit(failure(operation, 5, mount_error or "Docker workspace mount validation failed", log=str(log), workspace=str(workspace), container=selected_name, plan=plan), args.Json)
    plan["container_isolation"] = {
        "valid": True,
        "stage": "selected",
        "container": selected_name,
        "failure": None,
    }
    plan.update(
        requested_container=requested_container,
        container=selected_name,
        container_id=validated_container_id,
        container_mounts=container_mounts_for_evidence(selected_document),
        isolated_workspace_container=selected_name != requested_container,
        container_created=container_created,
        validated_workspace_mount={
            "type": validated_mount.get("Type"),
            "source": canonical_host_path(str(validated_mount["Source"])),
            "destination": validated_mount.get("Destination"),
            "rw": validated_mount.get("RW"),
        },
    )

    cleanup_code, cleanup_output = docker_capture(
        ["exec", validated_container_id, "rm", "-rf", "--", artifact_path]
    )
    plan["artifact_cleanup"] = {
        "container_id": validated_container_id,
        "path": artifact_path,
        "exit_code": cleanup_code,
        "output": cleanup_output,
    }
    if cleanup_code != 0:
        return emit(failure(operation, cleanup_code, "Failed to clear the selected container artifact path", log=str(log), workspace=str(workspace), container=selected_name, container_id=validated_container_id, plan=plan), args.Json)

    exit_code, stdout, stderr = run_logged(["docker", "exec", validated_container_id, "bash", "-lc", plan["inner"]], log)
    artifact = None
    export_value = None
    if exit_code == 0:
        destination_relative = MPU_ARTIFACT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            ensure_workspace_output_directory(
                workspace_value,
                MPU_ARTIFACT_ROOT,
                label="MPU artifact output",
            )
            destination = ensure_workspace_output_directory(
                workspace_value,
                destination_relative,
                label="MPU artifact export directory",
            )
            validated_workspace_output_path(
                workspace_value,
                destination_relative,
                label="MPU artifact export directory",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return emit(
                failure(
                    operation,
                    5,
                    str(exc),
                    blocked=True,
                    log=str(log),
                    workspace=str(workspace),
                    container=selected_name,
                    container_id=validated_container_id,
                    plan=plan,
                ),
                args.Json,
            )
        source = f"{validated_container_id}:{artifact_path}"
        export_code, export_output = docker_capture(["cp", source, str(destination)], timeout=300)
        export_value = {"source": source, "container_id": validated_container_id, "destination": str(destination), "exit_code": export_code, "output": export_output}
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
    return emit(result(ok, operation, exit_code, workspace=str(workspace), container=selected_name, container_id=validated_container_id, container_started=container_started, container_created=container_created, mode=args.Mode, started_at=started, ended_at=now_iso(), log=str(log), plan=plan, success_marker=success_marker, first_failure=first_failure, artifact=artifact, artifact_export=export_value), args.Json)


if __name__ == "__main__":
    raise SystemExit(main())
