#!/usr/bin/env python3
"""Generate, validate, and create Trellis embedded task branches."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "trellis-branch-policy/v1"
DEVELOPER_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)*$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TASK_BRANCH_RE = re.compile(
    r"^(?P<developer>[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)*)-"
    r"(?P<task>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<date>[0-9]{8})$"
)
RESERVED_DEVELOPERS = {
    "ai",
    "bugfix",
    "chore",
    "claude",
    "codex",
    "docs",
    "feat",
    "feature",
    "fix",
    "grok",
    "hotfix",
    "refactor",
    "test",
}
PROTECTED_BRANCHES = {"main", "master", "dev", "baseline_dev"}
PROTECTED_PATTERNS = (re.compile(r"^release/[a-zA-Z0-9._-]+$"),)


def emit(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    elif value.get("ok"):
        print(value.get("branch", "ok"))
    else:
        print(value.get("first_failure", "branch policy failed"), file=sys.stderr)


def result(ok: bool, operation: str, exit_code: int = 0, **fields: Any) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "operation": operation,
        "exit_code": exit_code,
    }
    value.update(fields)
    return value


def valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def validate_branch(
    branch: str,
    expected_developer: str | None = None,
    allow_protected: bool = False,
) -> dict[str, Any]:
    if branch in PROTECTED_BRANCHES or any(pattern.fullmatch(branch) for pattern in PROTECTED_PATTERNS):
        if allow_protected:
            return result(True, "branch-check", branch=branch, kind="protected", writable_task_branch=False)
        return result(
            False,
            "branch-check",
            2,
            branch=branch,
            kind="protected",
            writable_task_branch=False,
            first_failure="Protected lifecycle branch is not a writable task branch",
        )
    match = TASK_BRANCH_RE.fullmatch(branch)
    if not match:
        return result(
            False,
            "branch-check",
            2,
            branch=branch,
            expected="<developer>-<task-slug>-<YYYYMMDD>",
            first_failure="Task branch does not match the canonical Trellis naming format",
        )
    developer = match.group("developer")
    if developer in RESERVED_DEVELOPERS:
        return result(
            False,
            "branch-check",
            2,
            branch=branch,
            developer=developer,
            first_failure="Task branch must identify the human owner, not a change type or model",
        )
    if expected_developer and developer != expected_developer:
        return result(
            False,
            "branch-check",
            2,
            branch=branch,
            developer=developer,
            expected_developer=expected_developer,
            first_failure="Task branch developer does not match the task owner",
        )
    date = match.group("date")
    if not valid_date(date):
        return result(False, "branch-check", 2, branch=branch, first_failure="Task branch date is not a valid YYYYMMDD date")
    return result(
        True,
        "branch-check",
        branch=branch,
        kind="task",
        developer=developer,
        task=match.group("task"),
        date=date,
    )


def build_branch(developer: str, task: str, component: str | None, date: str) -> dict[str, Any]:
    if not DEVELOPER_RE.fullmatch(developer) or developer in RESERVED_DEVELOPERS:
        return result(False, "branch-format", 2, first_failure="Invalid or reserved --developer identifier")
    if not SLUG_RE.fullmatch(task):
        return result(False, "branch-format", 2, first_failure="--task must be a lowercase ASCII kebab-case slug")
    if component and not SLUG_RE.fullmatch(component):
        return result(False, "branch-format", 2, first_failure="--component must be a lowercase ASCII kebab-case slug")
    if not valid_date(date):
        return result(False, "branch-format", 2, first_failure="--date must be a valid YYYYMMDD date")
    slug = f"{task}-{component}" if component else task
    branch = f"{developer}-{slug}-{date}"
    return result(True, "branch-format", branch=branch, developer=developer, task=slug, date=date)


def git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )


def current_branch(repo: Path) -> str | None:
    completed = git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    return completed.stdout.strip() if completed.returncode == 0 else None


def command_format(args: argparse.Namespace) -> int:
    value = build_branch(args.developer, args.task, args.component, args.date)
    emit(value, args.json)
    return int(value["exit_code"])


def command_check(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    branch = args.branch or current_branch(repo)
    if not branch:
        value = result(False, "branch-check", 2, repository=str(repo), first_failure="Repository is detached or has no current branch")
    else:
        value = validate_branch(branch, args.developer, args.allow_protected)
        value["repository"] = str(repo)
    emit(value, args.json)
    return int(value["exit_code"])


def command_create(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    formatted = build_branch(args.developer, args.task, args.component, args.date)
    if not formatted["ok"]:
        emit(formatted, args.json)
        return int(formatted["exit_code"])
    branch = str(formatted["branch"])
    root = git(repo, ["rev-parse", "--show-toplevel"])
    if root.returncode != 0:
        value = result(False, "branch-create", 2, repository=str(repo), branch=branch, first_failure="Not a Git worktree")
        emit(value, args.json)
        return 2
    status = git(repo, ["status", "--porcelain=v1"])
    if status.returncode != 0 or status.stdout.strip():
        value = result(False, "branch-create", 4, repository=str(repo), branch=branch, dirty=True, first_failure="Create task branches only from a clean worktree")
        emit(value, args.json)
        return 4
    if args.base.startswith("-") or any(char in args.base for char in "\r\n\x00"):
        value = result(False, "branch-create", 2, repository=str(repo), branch=branch, first_failure="Invalid --base revision")
        emit(value, args.json)
        return 2
    base = git(repo, ["rev-parse", "--verify", f"{args.base}^{{commit}}"])
    if base.returncode != 0:
        value = result(False, "branch-create", 2, repository=str(repo), branch=branch, base=args.base, first_failure="Base revision does not resolve to a Commit")
        emit(value, args.json)
        return 2
    exists = git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    if exists.returncode == 0:
        value = result(False, "branch-create", 4, repository=str(repo), branch=branch, first_failure="Task branch already exists")
        emit(value, args.json)
        return 4
    created = git(repo, ["switch", "--no-track", "-c", branch, args.base])
    if created.returncode != 0:
        value = result(False, "branch-create", created.returncode, repository=str(repo), branch=branch, base=args.base, first_failure=created.stderr.strip() or "git switch failed")
        emit(value, args.json)
        return int(value["exit_code"])
    value = result(
        True,
        "branch-create",
        repository=str(repo),
        branch=branch,
        base=args.base,
        base_commit=base.stdout.strip(),
        upstream=None,
        pushed=False,
    )
    emit(value, args.json)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    json_requested = "--json" in argv
    argv = [argument for argument in argv if argument != "--json"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    format_parser = sub.add_parser("format")
    format_parser.add_argument("--developer", required=True)
    format_parser.add_argument("--task", required=True)
    format_parser.add_argument("--component")
    format_parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    format_parser.set_defaults(func=command_format)

    check_parser = sub.add_parser("check")
    check_parser.add_argument("--repo", type=Path, default=Path.cwd())
    check_parser.add_argument("--branch")
    check_parser.add_argument("--developer")
    check_parser.add_argument("--allow-protected", action="store_true")
    check_parser.set_defaults(func=command_check)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("--repo", type=Path, default=Path.cwd())
    create_parser.add_argument("--developer", required=True)
    create_parser.add_argument("--task", required=True)
    create_parser.add_argument("--component")
    create_parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    create_parser.add_argument("--base", required=True)
    create_parser.set_defaults(func=command_create)
    args = parser.parse_args(argv)
    args.json = json_requested or args.json
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
