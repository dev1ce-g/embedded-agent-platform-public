"""Windows-local embedded agent.

This CLI owns Windows project background, discovery, build/log bridge calls and
device-operation gates. Authorized local or remote Agents consume its JSON
Interface instead of constructing toolchain-specific commands.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from embedded_runtime_common import (
    DEFAULT_AGENTCTL,
    DEFAULT_GIT_BYTES,
    DEFAULT_GIT_TIMEOUT,
    DEFAULT_LOG_IMPORT_MAX_BYTES,
    DEFAULT_LOG_QUERY_BYTES,
    DEFAULT_READ_BYTES,
    DEFAULT_ROOT,
    DEFAULT_SDK_MANAGER,
    DEFAULT_TAIL_BYTES,
    DEFAULT_TOOL_SEARCH_BYTES,
    print_result,
    result,
    safe_project_id,
)
from embedded_runtime_device import command_device
from embedded_runtime_diagnose import command_diagnose
from embedded_runtime_can import command_can
from embedded_runtime_git import command_git
from embedded_runtime_jenkins import command_artifact, command_jenkins, command_job
from embedded_runtime_knowledge import command_knowledge, command_project, command_status
from embedded_runtime_operations import command_build, command_flash, command_log, command_rtt
from embedded_runtime_sdk import command_sdk
from embedded_runtime_tools import command_tool

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--agentctl", type=Path, default=DEFAULT_AGENTCTL)
    parser.add_argument("--sdk-manager", type=Path, default=DEFAULT_SDK_MANAGER)
    parser.add_argument("--json", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=command_status)

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="project_action", required=True)
    discover = project_sub.add_parser("discover")
    discover.add_argument("--project", required=True)
    discover.add_argument("--workspace", required=True)
    discover.add_argument("--keil-project", "--mcu-keil-project", dest="mcu_keil_project")
    discover.add_argument("--write-background", action="store_true")
    discover.set_defaults(func=command_project)
    show = project_sub.add_parser("show")
    show.add_argument("--project", required=True)
    show.set_defaults(func=command_project)
    stale = project_sub.add_parser("check-stale")
    stale.add_argument("--project", required=True)
    stale.set_defaults(func=command_project)

    device = sub.add_parser("device")
    device_sub = device.add_subparsers(dest="device_action", required=True)
    device_list = device_sub.add_parser("list")
    device_list.add_argument("--project", required=True)
    device_list.add_argument("--timeout", type=int, default=15)
    device_list.set_defaults(func=command_device)
    serial_inspect = device_sub.add_parser("serial-inspect")
    serial_inspect.add_argument("--project", required=True)
    serial_inspect.add_argument("--serial")
    serial_inspect.add_argument("--tty", required=True)
    serial_inspect.add_argument("--timeout", type=int, default=15)
    serial_inspect.set_defaults(func=command_device)

    diagnose = sub.add_parser("diagnose")
    diagnose_sub = diagnose.add_subparsers(dest="diagnose_action", required=True)
    process_list = diagnose_sub.add_parser("process-list")
    process_list.add_argument("--name", required=True)
    process_list.set_defaults(func=command_diagnose)
    process_stop = diagnose_sub.add_parser("process-stop")
    process_stop.add_argument("--name", required=True)
    process_stop.add_argument("--pid", type=int, required=True)
    process_stop.add_argument("--require-confirm", action="store_true")
    process_stop.add_argument("--confirm", action="store_true")
    process_stop.set_defaults(func=command_diagnose)

    jenkins = sub.add_parser("jenkins")
    jenkins.add_argument("--connection-id", required=True)
    jenkins.add_argument("--timeout", type=int, default=20)
    jenkins_sub = jenkins.add_subparsers(dest="jenkins_action", required=True)
    jenkins_auth = jenkins_sub.add_parser("auth-check")
    jenkins_auth.set_defaults(func=command_jenkins)
    jenkins_job = jenkins_sub.add_parser("job-inspect")
    jenkins_job.add_argument("--job", required=True)
    jenkins_job.set_defaults(func=command_jenkins)
    jenkins_parameters = jenkins_sub.add_parser("parameters")
    jenkins_parameters.add_argument("--job", required=True)
    jenkins_parameters.add_argument("--build", required=True, type=int)
    jenkins_parameters.set_defaults(func=command_jenkins)
    for action in ("build-status", "build-wait"):
        jenkins_status = jenkins_sub.add_parser(action)
        jenkins_status.add_argument("--job", required=True)
        jenkins_status.add_argument("--build", required=True, type=int)
        jenkins_status.add_argument("--wait-timeout", type=int, default=2700)
        jenkins_status.add_argument("--poll-interval", type=int, default=10)
        jenkins_status.add_argument("--max-chars", type=int, default=12000)
        jenkins_status.set_defaults(func=command_jenkins)
    jenkins_console = jenkins_sub.add_parser("console-tail")
    jenkins_console.add_argument("--job", required=True)
    jenkins_console.add_argument("--build", required=True, type=int)
    jenkins_console.add_argument("--max-chars", type=int, default=12000)
    jenkins_console.set_defaults(func=command_jenkins)
    jenkins_build = jenkins_sub.add_parser("build-start")
    jenkins_build.add_argument("--job", required=True)
    jenkins_build.add_argument("--from-build", required=True, type=int)
    jenkins_build.add_argument("--set", dest="set_values", action="append", default=[])
    jenkins_build.add_argument("--queue-timeout", type=int, default=120)
    jenkins_build.add_argument("--confirm", action="store_true")
    jenkins_build.set_defaults(func=command_jenkins)

    artifact = sub.add_parser("artifact")
    artifact.add_argument("--timeout", type=int, default=300)
    artifact_sub = artifact.add_subparsers(dest="artifact_action", required=True)
    artifact_download = artifact_sub.add_parser("download")
    artifact_download.add_argument("--connection-id", required=True)
    artifact_download.add_argument("--project", required=True)
    artifact_download.add_argument("--url", required=True)
    artifact_download.add_argument("--to", required=True)
    artifact_download.add_argument("--sha256", required=True)
    artifact_download.add_argument("--max-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    artifact_download.add_argument("--confirm", action="store_true")
    artifact_download.set_defaults(func=command_artifact)

    knowledge = sub.add_parser("knowledge")
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_action", required=True)
    knowledge_build = knowledge_sub.add_parser("build")
    knowledge_build.add_argument("--project", required=True)
    knowledge_build.add_argument("--write", action="store_true")
    knowledge_build.set_defaults(func=command_knowledge)
    knowledge_show = knowledge_sub.add_parser("show")
    knowledge_show.add_argument("--project", required=True)
    knowledge_show.set_defaults(func=command_knowledge)

    tool = sub.add_parser("tool")
    tool_sub = tool.add_subparsers(dest="tool_action", required=True)
    resolve_path = tool_sub.add_parser("resolve-path")
    resolve_path.add_argument("--project", required=True)
    resolve_path.add_argument("--path", default=".")
    resolve_path.set_defaults(func=command_tool)

    stat = tool_sub.add_parser("stat")
    stat.add_argument("--project", required=True)
    stat.add_argument("--path", required=True)
    stat.add_argument("--sha256", action="store_true")
    stat.set_defaults(func=command_tool)

    list_dir = tool_sub.add_parser("list")
    list_dir.add_argument("--project", required=True)
    list_dir.add_argument("--path", default=".")
    list_dir.add_argument("--max-entries", type=int, default=200)
    list_dir.set_defaults(func=command_tool)

    find = tool_sub.add_parser("find")
    find.add_argument("--project", required=True)
    find.add_argument("--root", dest="tool_root", default=".")
    find.add_argument("--glob", required=True)
    find.add_argument("--max-count", type=int, default=200)
    find.set_defaults(func=command_tool)

    rg = tool_sub.add_parser("rg")
    rg.add_argument("--project", required=True)
    rg.add_argument("--pattern", required=True)
    rg.add_argument("--root", dest="tool_root", default=".")
    rg.add_argument("--glob")
    rg.add_argument("--max-count", type=int, default=200)
    rg.add_argument("--max-bytes", type=int, default=DEFAULT_TOOL_SEARCH_BYTES)
    rg.add_argument("--regex", action="store_true")
    rg.add_argument("--ignore-case", action="store_true")
    rg.set_defaults(func=command_tool)

    read = tool_sub.add_parser("read")
    read.add_argument("--project", required=True)
    read.add_argument("--path", required=True)
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--max-bytes", type=int, default=DEFAULT_READ_BYTES)
    read.add_argument("--encoding", default="auto")
    read.add_argument("--binary", action="store_true")
    read.set_defaults(func=command_tool)

    tail_tool = tool_sub.add_parser("tail")
    tail_tool.add_argument("--project", required=True)
    tail_tool.add_argument("--path", required=True)
    tail_tool.add_argument("--lines", type=int, default=200)
    tail_tool.add_argument("--encoding", default="auto")
    tail_tool.set_defaults(func=command_tool)

    first_failure = tool_sub.add_parser("first-failure")
    first_failure.add_argument("--project", required=True)
    first_failure.add_argument("--path", required=True)
    first_failure.add_argument("--max-bytes", type=int, default=DEFAULT_TAIL_BYTES)
    first_failure.add_argument("--encoding", default="auto")
    first_failure.set_defaults(func=command_tool)

    git = sub.add_parser("git")
    git_sub = git.add_subparsers(dest="git_action", required=True)

    git_clone_parser = git_sub.add_parser("clone")
    git_clone_parser.add_argument("--project", required=True)
    git_clone_parser.add_argument("--workspace", required=True)
    git_clone_parser.add_argument("--url", required=True)
    git_clone_parser.add_argument("--path", required=True)
    git_clone_revision = git_clone_parser.add_mutually_exclusive_group(required=True)
    git_clone_revision.add_argument("--commit")
    git_clone_revision.add_argument("--branch")
    git_clone_parser.add_argument("--confirm", action="store_true")
    git_clone_parser.add_argument("--timeout", type=int, default=600)
    git_clone_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_clone_parser.set_defaults(func=command_git)

    git_sync_parser = git_sub.add_parser("sync")
    git_sync_parser.add_argument("--project", required=True)
    git_sync_parser.add_argument("--path", dest="git_path", required=True)
    git_sync_parser.add_argument("--commit", required=True)
    git_sync_parser.add_argument("--allow-dirty", action="store_true")
    git_sync_parser.add_argument("--confirm", action="store_true")
    git_sync_parser.add_argument("--timeout", type=int, default=600)
    git_sync_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_sync_parser.set_defaults(func=command_git)

    git_switch_parser = git_sub.add_parser("switch")
    git_switch_parser.add_argument("--project", required=True)
    git_switch_parser.add_argument("--path", dest="git_path", required=True)
    git_switch_parser.add_argument("--branch", required=True)
    git_switch_parser.add_argument("--commit", required=True)
    git_switch_parser.add_argument("--confirm", action="store_true")
    git_switch_parser.add_argument("--timeout", type=int, default=600)
    git_switch_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_switch_parser.set_defaults(func=command_git)

    git_create_branch_parser = git_sub.add_parser("create-branch")
    git_create_branch_parser.add_argument("--project", required=True)
    git_create_branch_parser.add_argument("--path", dest="git_path", required=True)
    git_create_branch_parser.add_argument("--branch", required=True)
    git_create_branch_parser.add_argument("--commit", required=True)
    git_create_branch_parser.add_argument("--confirm", action="store_true")
    git_create_branch_parser.add_argument("--timeout", type=int, default=600)
    git_create_branch_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_create_branch_parser.set_defaults(func=command_git)

    git_commit_parser = git_sub.add_parser("commit")
    git_commit_parser.add_argument("--project", required=True)
    git_commit_parser.add_argument("--path", dest="git_path", required=True)
    git_commit_parser.add_argument("--branch", required=True)
    git_commit_parser.add_argument("--message", required=True)
    git_commit_parser.add_argument("--include", action="append", required=True)
    git_commit_parser.add_argument("--confirm", action="store_true")
    git_commit_parser.add_argument("--timeout", type=int, default=600)
    git_commit_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_commit_parser.set_defaults(func=command_git)

    git_root_parser = git_sub.add_parser("root")
    git_root_parser.add_argument("--project", required=True)
    git_root_parser.add_argument("--root", dest="git_root", default=".")
    git_root_parser.set_defaults(func=command_git)

    git_status_parser = git_sub.add_parser("status")
    git_status_parser.add_argument("--project", required=True)
    git_status_parser.add_argument("--root", dest="git_root", default=".")
    git_status_parser.add_argument("--max-count", type=int, default=200)
    git_status_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_status_parser.set_defaults(func=command_git)

    git_diff_summary_parser = git_sub.add_parser("diff-summary")
    git_diff_summary_parser.add_argument("--project", required=True)
    git_diff_summary_parser.add_argument("--root", dest="git_root", default=".")
    git_diff_summary_parser.add_argument("--staged", action="store_true")
    git_diff_summary_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_diff_summary_parser.add_argument("--timeout", type=int, default=DEFAULT_GIT_TIMEOUT)
    git_diff_summary_parser.set_defaults(func=command_git)

    git_diff_parser = git_sub.add_parser("diff")
    git_diff_parser.add_argument("--project", required=True)
    git_diff_parser.add_argument("--root", dest="git_root", default=".")
    git_diff_parser.add_argument("--path")
    git_diff_parser.add_argument("--staged", action="store_true")
    git_diff_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_diff_parser.add_argument("--timeout", type=int, default=DEFAULT_GIT_TIMEOUT)
    git_diff_parser.set_defaults(func=command_git)

    git_log_parser = git_sub.add_parser("log")
    git_log_parser.add_argument("--project", required=True)
    git_log_parser.add_argument("--root", dest="git_root", default=".")
    git_log_parser.add_argument("--limit", type=int, default=20)
    git_log_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_log_parser.add_argument("--timeout", type=int, default=DEFAULT_GIT_TIMEOUT)
    git_log_parser.set_defaults(func=command_git)

    git_show_parser = git_sub.add_parser("show")
    git_show_parser.add_argument("--project", required=True)
    git_show_parser.add_argument("--root", dest="git_root", default=".")
    git_show_parser.add_argument("--rev", default="HEAD")
    git_show_parser.add_argument("--stat", action="store_true")
    git_show_parser.add_argument("--no-patch", action="store_true")
    git_show_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_show_parser.add_argument("--timeout", type=int, default=DEFAULT_GIT_TIMEOUT)
    git_show_parser.set_defaults(func=command_git)

    git_ls_files_parser = git_sub.add_parser("ls-files")
    git_ls_files_parser.add_argument("--project", required=True)
    git_ls_files_parser.add_argument("--root", dest="git_root", default=".")
    git_ls_files_parser.add_argument("--glob")
    git_ls_files_parser.add_argument("--max-count", type=int, default=200)
    git_ls_files_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    git_ls_files_parser.add_argument("--timeout", type=int, default=DEFAULT_GIT_TIMEOUT)
    git_ls_files_parser.set_defaults(func=command_git)

    sdk = sub.add_parser("sdk")
    sdk_sub = sdk.add_subparsers(dest="sdk_action", required=True)

    sdk_status_parser = sdk_sub.add_parser("status")
    sdk_status_parser.add_argument("--timeout", type=int, default=30)
    sdk_status_parser.add_argument("--max-bytes", type=int, default=8192)
    sdk_status_parser.set_defaults(func=command_sdk)

    sdk_list_parser = sdk_sub.add_parser("list")
    sdk_list_parser.add_argument("--timeout", type=int, default=60)
    sdk_list_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    sdk_list_parser.set_defaults(func=command_sdk)

    sdk_search_parser = sdk_sub.add_parser("search")
    sdk_search_parser.add_argument("--query", required=True)
    sdk_search_parser.add_argument("--limit", type=int, default=10)
    sdk_search_parser.add_argument("--timeout", type=int, default=120)
    sdk_search_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
    sdk_search_parser.set_defaults(func=command_sdk)

    sdk_components_parser = sdk_sub.add_parser("components")
    sdk_components_parser.add_argument("--sdk", required=True)
    sdk_components_parser.add_argument("--component", default=".")
    sdk_components_parser.add_argument("--max-entries", type=int, default=200)
    sdk_components_parser.set_defaults(func=command_sdk)

    for sdk_action in ("project-resolve", "project-pull"):
        sdk_project_parser = sdk_sub.add_parser(sdk_action)
        sdk_project_parser.add_argument("--project", required=True)
        sdk_project_parser.add_argument("--ci-dir")
        sdk_project_parser.add_argument("--query")
        sdk_project_parser.add_argument("--sdk-name")
        sdk_project_parser.add_argument("--sdk-version")
        sdk_project_parser.add_argument("--version")
        sdk_project_parser.add_argument("--confirm", action="store_true")
        sdk_project_parser.add_argument("--timeout", type=int, default=1800)
        sdk_project_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
        sdk_project_parser.set_defaults(func=command_sdk)

    for sdk_action in ("materialize", "check-mapping"):
        sdk_mapping_parser = sdk_sub.add_parser(sdk_action)
        sdk_mapping_parser.add_argument("--project", required=True)
        sdk_mapping_parser.add_argument("--sdk", required=True)
        sdk_mapping_parser.add_argument("--component", required=True)
        sdk_mapping_parser.add_argument("--to", required=True)
        sdk_mapping_parser.add_argument("--mode", choices=["junction", "copy"], default="junction")
        sdk_mapping_parser.add_argument("--confirm", action="store_true")
        sdk_mapping_parser.add_argument("--replace-managed", action="store_true")
        sdk_mapping_parser.add_argument("--timeout", type=int, default=1800)
        sdk_mapping_parser.add_argument("--max-bytes", type=int, default=DEFAULT_GIT_BYTES)
        sdk_mapping_parser.set_defaults(func=command_sdk)

    job = sub.add_parser("job")
    job_sub = job.add_subparsers(dest="job_action", required=True)
    job_start = job_sub.add_parser("start")
    job_start.add_argument("--project", required=True)
    job_start.add_argument("--kind", required=True, choices=["build", "jenkins-wait"])
    job_start.add_argument("--target", choices=["keil", "mcu", "mpu"])
    job_start.add_argument("--sdk-path")
    job_start.add_argument("--job", dest="jenkins_job")
    job_start.add_argument("--build", type=int)
    job_start.add_argument("--connection-id")
    job_start.add_argument("--timeout", type=int, default=20)
    job_start.add_argument("--wait-timeout", type=int, default=2700)
    job_start.add_argument("--poll-interval", type=int, default=10)
    job_start.add_argument("--max-chars", type=int, default=12000)
    job_start.set_defaults(func=command_job)

    job_status = job_sub.add_parser("status")
    job_status.add_argument("--job-id", required=True)
    job_status.set_defaults(func=command_job)

    job_output = job_sub.add_parser("output")
    job_output.add_argument("--job-id", required=True)
    job_output.add_argument("--stream", choices=["stdout", "stderr", "runner"], default="stdout")
    job_output.add_argument("--offset", type=int, default=0)
    job_output.add_argument("--max-bytes", type=int, default=DEFAULT_READ_BYTES)
    job_output.set_defaults(func=command_job)

    job_cancel = job_sub.add_parser("cancel")
    job_cancel.add_argument("--job-id", required=True)
    job_cancel.add_argument("--confirm", action="store_true")
    job_cancel.set_defaults(func=command_job)

    job_list = job_sub.add_parser("list")
    job_list.add_argument("--project")
    job_list.add_argument("--limit", type=int, default=20)
    job_list.set_defaults(func=command_job)

    build = sub.add_parser("build")
    build.add_argument("--project", required=True)
    build.add_argument("--target", required=True, choices=["keil", "mcu", "mpu"])
    build.add_argument("--sdk-path")
    build.add_argument("--dry-run", action="store_true")
    build.set_defaults(func=command_build)

    log = sub.add_parser("log")
    log_sub = log.add_subparsers(dest="log_action", required=True)
    tail = log_sub.add_parser("tail")
    tail.add_argument("--project", required=True)
    tail.add_argument("--kind", default="build")
    tail.add_argument("--since", default="10m")
    tail.add_argument("--dry-run", action="store_true")
    tail.set_defaults(func=command_log)

    log_import = log_sub.add_parser("import")
    log_import.add_argument("--project", required=True)
    log_import.add_argument("--task", required=True)
    log_import.add_argument("--label", required=True)
    log_import.add_argument("--source", required=True)
    log_import.add_argument("--encoding", default="auto")
    log_import.add_argument("--max-bytes", type=int, default=DEFAULT_LOG_IMPORT_MAX_BYTES)
    log_import.add_argument("--confirm", action="store_true")
    log_import.set_defaults(func=command_log)

    log_stat = log_sub.add_parser("stat")
    log_stat.add_argument("--project", required=True)
    log_stat.add_argument("--artifact", required=True)
    log_stat.set_defaults(func=command_log)

    log_read = log_sub.add_parser("read")
    log_read.add_argument("--project", required=True)
    log_read.add_argument("--artifact", required=True)
    log_read.add_argument("--offset", type=int, default=0)
    log_read.add_argument("--max-bytes", type=int, default=DEFAULT_READ_BYTES)
    log_read.add_argument("--encoding", default="auto")
    log_read.add_argument("--binary", action="store_true")
    log_read.set_defaults(func=command_log)

    log_rg = log_sub.add_parser("rg")
    log_rg.add_argument("--project", required=True)
    log_rg.add_argument("--artifact", required=True)
    log_rg.add_argument("--pattern", required=True)
    log_rg.add_argument("--max-count", type=int, default=200)
    log_rg.add_argument("--max-bytes", type=int, default=DEFAULT_LOG_QUERY_BYTES)
    log_rg.add_argument("--encoding", default="auto")
    log_rg.add_argument("--regex", action="store_true")
    log_rg.add_argument("--ignore-case", action="store_true")
    log_rg.set_defaults(func=command_log)

    log_context = log_sub.add_parser("context")
    log_context.add_argument("--project", required=True)
    log_context.add_argument("--artifact", required=True)
    log_context.add_argument("--line", type=int, required=True)
    log_context.add_argument("--before", type=int, default=40)
    log_context.add_argument("--after", type=int, default=40)
    log_context.add_argument("--max-bytes", type=int, default=DEFAULT_LOG_QUERY_BYTES)
    log_context.add_argument("--encoding", default="auto")
    log_context.set_defaults(func=command_log)

    can = sub.add_parser("can")
    can_sub = can.add_subparsers(dest="can_action", required=True)
    can_sub.add_parser("driver-list").set_defaults(func=command_can)
    can_probe = can_sub.add_parser("driver-probe")
    can_probe.add_argument("--driver", required=True)
    can_probe.set_defaults(func=command_can)
    can_device_probe = can_sub.add_parser("device-probe")
    can_device_probe.add_argument("--driver", choices=("controlcan", "zcanpro"), default="controlcan")
    can_device_probe.add_argument("--dll")
    can_device_probe.add_argument("--device-model", action="append", default=[])
    can_device_probe.add_argument("--device-index", type=int, action="append", default=[])
    can_device_probe.add_argument("--timeout", type=int, default=30)
    can_device_probe.set_defaults(func=command_can)
    can_self_test = can_sub.add_parser("self-test")
    can_self_test.add_argument("--timeout", type=int, default=30)
    can_self_test.set_defaults(func=command_can)

    can_actions = {}
    for action in ("check-env", "monitor", "send", "uds-ecu", "uds-tester"):
        can_action = can_sub.add_parser(action)
        can_action.add_argument("--driver", choices=("controlcan", "zcanpro", "virtual"), default="controlcan")
        can_action.add_argument("--channel", type=int, default=0)
        can_action.add_argument("--bitrate", type=int, default=500000)
        can_action.add_argument("--dll")
        can_action.add_argument("--device-model")
        can_action.add_argument("--device-index", type=int, default=0)
        can_action.add_argument("--timeout", type=int, default=60)
        can_action.set_defaults(func=command_can)
        can_actions[action] = can_action

    can_monitor = can_actions["monitor"]
    can_monitor.add_argument("--duration", type=float)
    can_monitor.add_argument("--count", type=int)
    can_monitor.add_argument("--id", dest="can_id", action="append", default=[])
    can_monitor.add_argument("--exclude-id", action="append", default=[])

    can_send = can_actions["send"]
    can_send.add_argument("--frame", action="append", required=True)
    can_send.add_argument("--count", type=int, default=1)
    can_send.add_argument("--period-ms", type=int, default=0)
    can_send.add_argument("--require-confirm", action="store_true")
    can_send.add_argument("--confirm", action="store_true")

    can_ecu = can_actions["uds-ecu"]
    can_ecu.add_argument("--rxid", default="0x660")
    can_ecu.add_argument("--txid", default="0x668")
    can_ecu.add_argument("--profile", default="golden")
    can_ecu.add_argument("--idle-timeout", type=float)
    can_ecu.add_argument("--max-requests", type=int)
    can_ecu.add_argument("--require-confirm", action="store_true")
    can_ecu.add_argument("--confirm", action="store_true")

    can_tester = can_actions["uds-tester"]
    can_tester.add_argument("--rxid", default="0x668")
    can_tester.add_argument("--txid", default="0x660")
    can_tester.add_argument("--request", action="append", required=True)
    can_tester.add_argument("--expect", action="append", default=[])
    can_tester.add_argument("--response-timeout", type=float, default=5.0)
    can_tester.add_argument("--require-confirm", action="store_true")
    can_tester.add_argument("--confirm", action="store_true")

    rtt = sub.add_parser("rtt")
    rtt_sub = rtt.add_subparsers(dest="rtt_action", required=True)
    capture = rtt_sub.add_parser("capture")
    capture.add_argument("--project", required=True)
    capture.add_argument("--target", required=True, choices=["mcu"])
    capture.add_argument("--wait-ms", type=int, default=12000)
    capture.add_argument("--reset", action="store_true")
    capture.add_argument("--require-confirm", action="store_true")
    capture.add_argument("--confirm", action="store_true")
    capture.set_defaults(func=command_rtt)

    flash = sub.add_parser("flash")
    flash.add_argument("--project", required=True)
    flash.add_argument("--target", required=True, choices=["mcu", "mpu"])
    flash.add_argument("--package", type=Path)
    flash.add_argument("--connection-id")
    flash.add_argument("--port", action="append", default=[])
    flash.add_argument("--usb-only", action="store_true")
    flash.add_argument("--auto-enable", action="store_true")
    flash.add_argument("--speed", type=int, default=115200)
    flash.add_argument("--reboot", action="store_true")
    flash.add_argument("--at-fallback", action="store_true")
    flash.add_argument("--timeout", type=int, default=1800)
    flash.add_argument("--require-confirm", action="store_true")
    flash.add_argument("--confirm", action="store_true")
    flash.set_defaults(func=command_flash)
    return parser

def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    json_requested = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    parser = build_parser()
    args = parser.parse_args(argv)
    args.json = json_requested or args.json
    project = getattr(args, "project", None)
    if project is not None:
        try:
            safe_project_id(project)
        except ValueError as error:
            print_result(
                result(False, "request-validation", 2, first_failure=str(error)),
                args.json,
            )
            return 2
    return args.func(args)
