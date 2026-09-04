"""Internal embedded runtime git module."""

from __future__ import annotations

from embedded_runtime_common import *

def git_clone(args: argparse.Namespace) -> int:
    operation = "git-clone"
    workspace = Path(args.workspace).expanduser().resolve()
    commit = getattr(args, "commit", None)
    branch = getattr(args, "branch", None)
    target, target_failure = clone_target(workspace, args.path)
    if target_failure:
        value = result(False, operation, 5, workspace=str(workspace), path=args.path, first_failure=target_failure)
        print_result(value, args.json)
        return 5
    assert target is not None
    if not valid_clone_url(args.url):
        value = result(False, operation, 2, workspace=str(workspace), path=args.path, first_failure="Only network Git URLs without embedded credentials are allowed")
        print_result(value, args.json)
        return 2
    if commit is not None and not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        value = result(False, operation, 2, workspace=str(workspace), path=args.path, commit=commit, first_failure="--commit must be a full 40-character SHA-1")
        print_result(value, args.json)
        return 2
    if branch is not None and not valid_clone_branch(branch):
        value = result(False, operation, 2, workspace=str(workspace), path=args.path, branch=branch, first_failure="--branch is not a valid Git branch name")
        print_result(value, args.json)
        return 2
    if target.exists():
        try:
            if any(target.iterdir()):
                value = result(False, operation, 4, workspace=str(workspace), path=args.path, normalized_path=str(target), first_failure="Clone target already exists and is not empty")
                print_result(value, args.json)
                return 4
        except OSError as exc:
            value = result(False, operation, 4, workspace=str(workspace), path=args.path, normalized_path=str(target), first_failure=str(exc))
            print_result(value, args.json)
            return 4
    if not args.confirm:
        value = result(False, operation, 3, workspace=str(workspace), path=args.path, normalized_path=str(target), requires_human_confirm=True, first_failure="Git clone changes the Windows workspace; rerun with --confirm")
        print_result(value, args.json)
        return 3
    if not workspace.exists():
        try:
            workspace.mkdir(parents=True)
        except OSError as exc:
            value = result(False, operation, 4, workspace=str(workspace), first_failure=f"Cannot create workspace: {exc}")
            print_result(value, args.json)
            return 4
    resolved_commit = commit
    if branch is not None:
        remote_ref = f"refs/heads/{branch}"
        try:
            remote = subprocess.run(
                ["git", "ls-remote", "--exit-code", "--heads", "--", args.url, remote_ref],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=max(1, args.timeout),
                env=git_env(),
            )
        except subprocess.TimeoutExpired:
            value = result(False, operation, 124, workspace=str(workspace), path=args.path, branch=branch, first_failure=f"git ls-remote timed out after {max(1, args.timeout)}s")
            print_result(value, args.json)
            return 124
        except OSError as exc:
            value = result(False, operation, 127, workspace=str(workspace), path=args.path, branch=branch, first_failure=str(exc))
            print_result(value, args.json)
            return 127
        if remote.returncode != 0:
            stderr, stderr_bytes, stderr_truncated = bounded_output(remote.stderr, args.max_bytes)
            value = result(False, operation, remote.returncode, workspace=str(workspace), path=args.path, branch=branch, stderr=stderr, stderr_bytes=stderr_bytes, truncated=stderr_truncated, first_failure=stderr.strip() or "Remote branch was not found")
            print_result(value, args.json)
            return remote.returncode
        remote_stdout = remote.stdout.decode("utf-8", errors="replace").strip().splitlines()
        if len(remote_stdout) != 1:
            value = result(False, operation, 6, workspace=str(workspace), path=args.path, branch=branch, first_failure="Remote branch did not resolve to exactly one ref")
            print_result(value, args.json)
            return 6
        remote_fields = remote_stdout[0].split()
        if len(remote_fields) != 2 or remote_fields[1] != remote_ref or not re.fullmatch(r"[0-9a-fA-F]{40}", remote_fields[0]):
            value = result(False, operation, 6, workspace=str(workspace), path=args.path, branch=branch, first_failure="Remote branch response is invalid")
            print_result(value, args.json)
            return 6
        resolved_commit = remote_fields[0]

    command = ["git", "clone"]
    if branch is not None:
        command.extend(["--branch", branch, "--single-branch"])
    command.extend(["--", args.url, str(target)])
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=max(1, args.timeout), env=git_env())
    except subprocess.TimeoutExpired:
        value = result(False, operation, 124, workspace=str(workspace), path=args.path, normalized_path=str(target), first_failure=f"git clone timed out after {max(1, args.timeout)}s")
        print_result(value, args.json)
        return 124
    except OSError as exc:
        value = result(False, operation, 127, workspace=str(workspace), path=args.path, normalized_path=str(target), first_failure=str(exc))
        print_result(value, args.json)
        return 127
    if completed.returncode != 0:
        stderr, stderr_bytes, stderr_truncated = bounded_output(completed.stderr, args.max_bytes)
        value = result(False, operation, completed.returncode, workspace=str(workspace), path=args.path, normalized_path=str(target), stderr=stderr, stderr_bytes=stderr_bytes, truncated=stderr_truncated, first_failure=stderr.strip() or "git clone failed")
        print_result(value, args.json)
        return completed.returncode
    if commit is not None:
        checkout = run_git_read(target, ["checkout", "--detach", commit], max_bytes=args.max_bytes, timeout=args.timeout)
    else:
        checkout = {"ok": True, "exit_code": 0, "first_failure": None}
    head = git_short_value(target, ["rev-parse", "HEAD"])
    current_branch = git_short_value(target, ["rev-parse", "--abbrev-ref", "HEAD"])
    upstream = git_short_value(target, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    expected_upstream = f"origin/{branch}" if branch is not None else None
    verified = head is not None and resolved_commit is not None and head.lower() == resolved_commit.lower()
    if branch is not None:
        verified = verified and current_branch == branch and upstream == expected_upstream
    if not checkout["ok"] or not verified:
        value = result(False, operation, checkout["exit_code"] or 1, workspace=str(workspace), path=args.path, normalized_path=str(target), branch=branch, commit=resolved_commit, head=head, current_branch=current_branch, upstream=upstream, verified=verified, checkout=checkout, first_failure=checkout["first_failure"] or "Checked out HEAD does not match requested revision")
        print_result(value, args.json)
        return int(value["exit_code"])
    value = result(True, operation, workspace=str(workspace), path=args.path, normalized_path=str(target), branch=branch, commit=resolved_commit, head=head, current_branch=current_branch, upstream=upstream, verified=True, detached=commit is not None, gate={"level": "L2", "requires_human_confirm": True, "confirmed": True})
    print_result(value, args.json)
    return 0

def valid_clone_branch(branch: str) -> bool:
    if not branch or branch.startswith("-"):
        return False
    try:
        completed = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
            env=git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0

def git_sync(args: argparse.Namespace, background: dict[str, Any]) -> int:
    operation = "git-sync"
    info, repo, failure = resolve_git_root(background, args.git_path)
    if failure:
        failure["operation"] = operation
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
        value = result(False, operation, 2, **git_repo_context(background, repo, info), commit=args.commit, first_failure="--commit must be a full 40-character SHA-1")
        print_result(value, args.json)
        return 2
    before = git_short_value(repo, ["rev-parse", "HEAD"])
    status = run_git_read(repo, ["status", "--porcelain=v1"], max_bytes=max(4096, args.max_bytes))
    if not status["ok"]:
        value = result(False, operation, status["exit_code"], **git_repo_context(background, repo, info), first_failure=status["first_failure"] or "Unable to read Git status")
        print_result(value, args.json)
        return int(value["exit_code"])
    if status["stdout"].strip() and not args.allow_dirty:
        value = result(False, operation, 4, **git_repo_context(background, repo, info), before=before, dirty=True, requires_allow_dirty=True, first_failure="Git workspace is dirty; rerun with --allow-dirty only after review")
        print_result(value, args.json)
        return 4
    if not args.confirm:
        value = result(False, operation, 3, **git_repo_context(background, repo, info), before=before, dirty=bool(status["stdout"].strip()), requires_human_confirm=True, first_failure="Git sync changes the working tree; rerun with --confirm")
        print_result(value, args.json)
        return 3
    remote = git_short_value(repo, ["remote", "get-url", "origin"])
    if not remote:
        value = result(False, operation, 2, **git_repo_context(background, repo, info), before=before, first_failure="Git remote origin is not configured")
        print_result(value, args.json)
        return 2
    fetch = run_git_read(repo, ["fetch", "--no-tags", "origin", args.commit], max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    if not fetch["ok"]:
        value = result(False, operation, fetch["exit_code"], **git_repo_context(background, repo, info), before=before, remote_configured=True, fetch=fetch, first_failure=fetch["first_failure"] or "Git fetch failed")
        print_result(value, args.json)
        return int(value["exit_code"])
    checkout = run_git_read(repo, ["checkout", "--detach", args.commit], max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    after = git_short_value(repo, ["rev-parse", "HEAD"])
    verified = after is not None and after.lower() == args.commit.lower()
    ok = checkout["ok"] and verified
    value = result(
        ok,
        operation,
        0 if ok else checkout["exit_code"] or 6,
        **git_repo_context(background, repo, info),
        before=before,
        after=after,
        commit=args.commit,
        verified=verified,
        detached=True,
        remote_configured=True,
        allow_dirty=args.allow_dirty,
        gate={"level": "L2", "requires_human_confirm": True, "confirmed": True},
        fetch={"ok": fetch["ok"], "exit_code": fetch["exit_code"], "truncated": fetch["truncated"]},
        checkout={"ok": checkout["ok"], "exit_code": checkout["exit_code"], "stderr": checkout["stderr"], "truncated": checkout["truncated"]},
        first_failure=None if ok else checkout["first_failure"] or "HEAD does not match requested Commit SHA",
    )
    append_run(agent_paths(args.root), background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def git_switch(args: argparse.Namespace, background: dict[str, Any]) -> int:
    operation = "git-switch"
    info, repo, failure = resolve_git_root(background, args.git_path)
    if failure:
        failure["operation"] = operation
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None

    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
        value = result(False, operation, 2, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, first_failure="--commit must be a full 40-character SHA-1")
        print_result(value, args.json)
        return 2
    branch_check = run_git_read(repo, ["check-ref-format", "--branch", args.branch], max_bytes=4096)
    if not branch_check["ok"] or args.branch.startswith("-"):
        value = result(False, operation, 2, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, first_failure="--branch is not a valid Git branch name")
        print_result(value, args.json)
        return 2

    status = run_git_read(repo, ["status", "--porcelain=v1"], max_bytes=max(4096, args.max_bytes))
    if not status["ok"]:
        value = result(False, operation, status["exit_code"], **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, first_failure=status["first_failure"] or "Unable to read Git status")
        print_result(value, args.json)
        return int(value["exit_code"])
    if status["stdout"].strip():
        value = result(False, operation, 4, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, dirty=True, first_failure="Git workspace is dirty; branch switch refused")
        print_result(value, args.json)
        return 4
    if not args.confirm:
        value = result(False, operation, 3, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, requires_human_confirm=True, first_failure="Git switch changes the Windows workspace; rerun with --confirm")
        print_result(value, args.json)
        return 3

    before_branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    before = git_short_value(repo, ["rev-parse", "HEAD"])
    remote = git_short_value(repo, ["remote", "get-url", "origin"])
    if not remote:
        value = result(False, operation, 2, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, before=before, first_failure="Git remote origin is not configured")
        print_result(value, args.json)
        return 2

    fetch = run_git_read(repo, ["fetch", "--no-tags", "origin", args.branch], max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    if not fetch["ok"]:
        value = result(False, operation, fetch["exit_code"], **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, before=before, fetch=fetch, first_failure=fetch["first_failure"] or "Git fetch failed")
        print_result(value, args.json)
        return int(value["exit_code"])

    remote_head = git_short_value(repo, ["rev-parse", "--verify", f"refs/remotes/origin/{args.branch}"])
    if remote_head is None or remote_head.lower() != args.commit.lower():
        value = result(False, operation, 6, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, before=before, remote_head=remote_head, verified=False, first_failure="Remote branch HEAD does not match requested Commit SHA")
        print_result(value, args.json)
        return 6

    local_head = git_short_value(repo, ["rev-parse", "--verify", f"refs/heads/{args.branch}"])
    created_local_branch = local_head is None
    if local_head is not None and local_head.lower() != args.commit.lower():
        value = result(False, operation, 6, **git_repo_context(background, repo, info), branch=args.branch, commit=args.commit, before=before, local_head=local_head, remote_head=remote_head, verified=False, first_failure="Existing local branch does not match requested Commit SHA; refusing branch rewrite")
        print_result(value, args.json)
        return 6

    switch_args = ["checkout", "-b", args.branch, "--track", f"origin/{args.branch}"] if created_local_branch else ["checkout", args.branch]
    switched = run_git_read(repo, switch_args, max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    after_branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    after = git_short_value(repo, ["rev-parse", "HEAD"])
    upstream = git_short_value(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    verified = switched["ok"] and after_branch == args.branch and after is not None and after.lower() == args.commit.lower() and upstream == f"origin/{args.branch}"
    value = result(
        verified,
        operation,
        0 if verified else switched["exit_code"] or 6,
        **git_repo_context(background, repo, info),
        branch=args.branch,
        commit=args.commit,
        before_branch=before_branch,
        before=before,
        after_branch=after_branch,
        after=after,
        upstream=upstream,
        remote_head=remote_head,
        created_local_branch=created_local_branch,
        verified=verified,
        dirty=False,
        gate={"level": "L2", "requires_human_confirm": True, "confirmed": True},
        fetch={"ok": fetch["ok"], "exit_code": fetch["exit_code"], "truncated": fetch["truncated"]},
        switch={"ok": switched["ok"], "exit_code": switched["exit_code"], "stderr": switched["stderr"], "truncated": switched["truncated"]},
        first_failure=None if verified else switched["first_failure"] or "Branch, upstream or Commit SHA verification failed",
    )
    append_run(agent_paths(args.root), background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def validate_git_branch(repo: Path, branch: str) -> bool:
    check = run_git_read(repo, ["check-ref-format", "--branch", branch], max_bytes=4096)
    return check["ok"] and not branch.startswith("-")

def git_create_branch(args: argparse.Namespace, background: dict[str, Any]) -> int:
    operation = "git-create-branch"
    info, repo, failure = resolve_git_root(background, args.git_path)
    if failure:
        failure["operation"] = operation
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None

    context = git_repo_context(background, repo, info)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
        value = result(False, operation, 2, **context, branch=args.branch, commit=args.commit, first_failure="--commit must be a full 40-character SHA-1")
        print_result(value, args.json)
        return 2
    if not validate_git_branch(repo, args.branch):
        value = result(False, operation, 2, **context, branch=args.branch, commit=args.commit, first_failure="--branch is not a valid Git branch name")
        print_result(value, args.json)
        return 2

    before = git_short_value(repo, ["rev-parse", "HEAD"])
    before_branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if before is None or before.lower() != args.commit.lower():
        value = result(False, operation, 6, **context, branch=args.branch, commit=args.commit, before=before, verified=False, first_failure="Current HEAD does not match requested Commit SHA")
        print_result(value, args.json)
        return 6
    if git_short_value(repo, ["rev-parse", "--verify", f"refs/heads/{args.branch}"]) is not None:
        value = result(False, operation, 4, **context, branch=args.branch, commit=args.commit, before=before, first_failure="Local branch already exists; refusing branch rewrite")
        print_result(value, args.json)
        return 4

    unmerged = run_git_read(repo, ["ls-files", "--unmerged"], max_bytes=max(4096, args.max_bytes))
    if not unmerged["ok"] or unmerged["stdout"].strip():
        value = result(False, operation, 4, **context, branch=args.branch, commit=args.commit, before=before, unmerged=bool(unmerged["stdout"].strip()), first_failure=unmerged["first_failure"] or "Git index contains unmerged entries")
        print_result(value, args.json)
        return 4
    status_before = run_git_read(repo, ["status", "--porcelain=v1"], max_bytes=max(4096, args.max_bytes))
    if not status_before["ok"]:
        value = result(False, operation, status_before["exit_code"], **context, branch=args.branch, commit=args.commit, first_failure=status_before["first_failure"] or "Unable to read Git status")
        print_result(value, args.json)
        return int(value["exit_code"])
    if not args.confirm:
        value = result(False, operation, 3, **context, branch=args.branch, commit=args.commit, before=before, dirty=bool(status_before["stdout"].strip()), requires_human_confirm=True, first_failure="Git branch creation changes repository state; rerun with --confirm")
        print_result(value, args.json)
        return 3

    created = run_git_read(repo, ["checkout", "-b", args.branch, args.commit], max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    after = git_short_value(repo, ["rev-parse", "HEAD"])
    after_branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    status_after = run_git_read(repo, ["status", "--porcelain=v1"], max_bytes=max(4096, args.max_bytes))
    worktree_preserved = status_after["ok"] and status_after["stdout"] == status_before["stdout"]
    verified = created["ok"] and after_branch == args.branch and after is not None and after.lower() == args.commit.lower() and worktree_preserved
    value = result(
        verified,
        operation,
        0 if verified else created["exit_code"] or status_after["exit_code"] or 6,
        **context,
        branch=args.branch,
        commit=args.commit,
        before_branch=before_branch,
        before=before,
        after_branch=after_branch,
        after=after,
        dirty=bool(status_before["stdout"].strip()),
        worktree_preserved=worktree_preserved,
        change_count=len(status_before["stdout"].splitlines()),
        verified=verified,
        gate={"level": "L2", "requires_human_confirm": True, "confirmed": True},
        create={"ok": created["ok"], "exit_code": created["exit_code"], "stderr": created["stderr"], "truncated": created["truncated"]},
        first_failure=None if verified else created["first_failure"] or status_after["first_failure"] or "Branch, Commit SHA or working-tree preservation verification failed",
    )
    append_run(agent_paths(args.root), background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def normalize_commit_include(repo: Path, value: str) -> tuple[str | None, str | None]:
    raw = value.strip().replace("\\", "/")
    if not raw or Path(raw).is_absolute() or re.match(r"^[A-Za-z]:[/\\]", raw):
        return None, "Commit include must be a non-empty repository-relative path"
    candidate = (repo / raw).resolve()
    if not is_relative_to(candidate, repo):
        return None, "Commit include is outside Git repository"
    if not candidate.exists():
        return None, "Commit include does not exist"
    return rel(candidate, repo), None

def git_commit_paths(args: argparse.Namespace, background: dict[str, Any]) -> int:
    operation = "git-commit"
    info, repo, failure = resolve_git_root(background, args.git_path)
    if failure:
        failure["operation"] = operation
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    context = git_repo_context(background, repo, info)

    if not validate_git_branch(repo, args.branch):
        value = result(False, operation, 2, **context, branch=args.branch, first_failure="--branch is not a valid Git branch name")
        print_result(value, args.json)
        return 2
    current_branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if current_branch != args.branch:
        value = result(False, operation, 6, **context, branch=args.branch, current_branch=current_branch, first_failure="Current branch does not match --branch")
        print_result(value, args.json)
        return 6
    message = args.message.strip()
    if not message or any(character in args.message for character in ("\r", "\n", "\x00")):
        value = result(False, operation, 2, **context, branch=args.branch, first_failure="--message must be a non-empty single line")
        print_result(value, args.json)
        return 2

    includes: list[str] = []
    for raw in args.include:
        normalized, include_failure = normalize_commit_include(repo, raw)
        if include_failure:
            value = result(False, operation, 5, **context, branch=args.branch, include=raw, first_failure=include_failure)
            print_result(value, args.json)
            return 5
        assert normalized is not None
        if normalized not in includes:
            includes.append(normalized)

    staged_before = run_git_read(repo, ["diff", "--cached", "--name-only"], max_bytes=max(4096, args.max_bytes))
    if not staged_before["ok"]:
        value = result(False, operation, staged_before["exit_code"], **context, branch=args.branch, first_failure=staged_before["first_failure"] or "Unable to inspect staged changes")
        print_result(value, args.json)
        return int(value["exit_code"])
    if staged_before["stdout"].strip():
        value = result(False, operation, 4, **context, branch=args.branch, staged_before=staged_before["stdout"].splitlines(), first_failure="Git index already contains staged changes")
        print_result(value, args.json)
        return 4
    if not args.confirm:
        value = result(False, operation, 3, **context, branch=args.branch, includes=includes, requires_human_confirm=True, first_failure="Git commit changes repository history; rerun with --confirm")
        print_result(value, args.json)
        return 3

    staged = run_git_read(repo, ["add", "--", *includes], max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    if not staged["ok"]:
        value = result(False, operation, staged["exit_code"], **context, branch=args.branch, includes=includes, first_failure=staged["first_failure"] or "Git add failed")
        print_result(value, args.json)
        return int(value["exit_code"])
    staged_names = run_git_read(repo, ["diff", "--cached", "--name-only"], max_bytes=max(4096, args.max_bytes))
    names = [name for name in staged_names["stdout"].splitlines() if name]
    unexpected = [name for name in names if not any(name == include or name.startswith(include.rstrip("/") + "/") for include in includes)]
    if not staged_names["ok"] or not names or unexpected:
        value = result(False, operation, 6, **context, branch=args.branch, includes=includes, staged_paths=names, unexpected_paths=unexpected, first_failure=staged_names["first_failure"] or "Staged paths are empty or exceed explicit includes; commit refused")
        append_run(agent_paths(args.root), background["project_id"], value)
        print_result(value, args.json)
        return 6

    before = git_short_value(repo, ["rev-parse", "HEAD"])
    committed = run_git_read(repo, ["commit", "-m", message], max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    after = git_short_value(repo, ["rev-parse", "HEAD"])
    after_branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    verified = committed["ok"] and after is not None and after != before and after_branch == args.branch
    remaining = run_git_read(repo, ["status", "--porcelain=v1"], max_bytes=max(4096, args.max_bytes))
    value = result(
        verified,
        operation,
        0 if verified else committed["exit_code"] or 6,
        **context,
        branch=args.branch,
        message=message,
        includes=includes,
        staged_paths=names,
        before=before,
        commit=after,
        after_branch=after_branch,
        verified=verified,
        remaining_changes=parse_porcelain_status(remaining["stdout"]) if remaining["ok"] else None,
        gate={"level": "L2", "requires_human_confirm": True, "confirmed": True},
        backend={"ok": committed["ok"], "exit_code": committed["exit_code"], "stdout": committed["stdout"], "stderr": committed["stderr"], "truncated": committed["truncated"]},
        first_failure=None if verified else committed["first_failure"] or "Commit or branch verification failed",
    )
    append_run(agent_paths(args.root), background["project_id"], value)
    print_result(value, args.json)
    return int(value["exit_code"])

def command_git(args: argparse.Namespace) -> int:
    if args.git_action == "clone":
        return git_clone(args)

    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(
            False,
            f"git-{args.git_action}",
            2,
            project_id=safe_project_id(args.project),
            first_failure="Project background not found",
            next_hint="Run project discover --write-background first",
        )
        print_result(value, args.json)
        return 2
    if args.git_action == "sync":
        return git_sync(args, background)
    if args.git_action == "switch":
        return git_switch(args, background)
    if args.git_action == "create-branch":
        return git_create_branch(args, background)
    if args.git_action == "commit":
        return git_commit_paths(args, background)

    handlers = {
        "root": git_root,
        "status": git_status,
        "diff-summary": git_diff_summary,
        "diff": git_diff,
        "log": git_log,
        "show": git_show,
        "ls-files": git_ls_files,
    }
    handler = handlers.get(args.git_action)
    if handler is None:
        value = result(False, "git", 2, project_id=background["project_id"], first_failure=f"Unknown git action: {args.git_action}")
        print_result(value, args.json)
        return 2
    return handler(args, background)

def git_root(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info, repo, failure = resolve_git_root(background, args.git_root)
    if failure:
        failure["operation"] = "git-root"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    value = result(
        True,
        "git-root",
        **git_repo_context(background, repo, info),
        inside_workspace=True,
    )
    print_result(value, args.json)
    return 0

def git_status(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info, repo, failure = resolve_git_root(background, args.git_root)
    if failure:
        failure["operation"] = "git-status"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    status_raw = run_git_read(repo, ["status", "--porcelain=v1", "--branch"], max_bytes=max(4096, args.max_bytes))
    if not status_raw["ok"]:
        value = result(False, "git-status", status_raw["exit_code"], **git_repo_context(background, repo, info), stderr=status_raw["stderr"], first_failure=status_raw["first_failure"])
        print_result(value, args.json)
        return int(value["exit_code"])
    changes = parse_porcelain_status(status_raw["stdout"])
    branch_info = parse_branch_status(status_raw["stdout"])
    branch = git_short_value(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    head = git_short_value(repo, ["rev-parse", "--short", "HEAD"])
    value = result(
        True,
        "git-status",
        **git_repo_context(background, repo, info),
        branch=branch_info.get("branch") or branch,
        upstream=branch_info.get("upstream"),
        head=head,
        dirty=bool(changes),
        ahead=branch_info.get("ahead", 0),
        behind=branch_info.get("behind", 0),
        changed_count=len(changes),
        changes=changes[:max(1, args.max_count)],
        truncated=len(changes) > max(1, args.max_count) or status_raw["truncated"],
    )
    print_result(value, args.json)
    return 0

def git_diff_summary(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info, repo, failure = resolve_git_root(background, args.git_root)
    if failure:
        failure["operation"] = "git-diff-summary"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    git_args = ["diff", "--stat", "--summary"]
    if args.staged:
        git_args.insert(1, "--cached")
    diff = run_git_read(repo, git_args, max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    ok = diff["exit_code"] == 0
    value = result(
        ok,
        "git-diff-summary",
        0 if ok else diff["exit_code"],
        **git_repo_context(background, repo, info),
        staged=args.staged,
        summary=diff["stdout"],
        stdout_bytes=diff["stdout_bytes"],
        stderr=diff["stderr"],
        truncated=diff["truncated"],
        first_failure=diff["first_failure"],
    )
    print_result(value, args.json)
    return int(value["exit_code"])

def git_diff(args: argparse.Namespace, background: dict[str, Any]) -> int:
    root_value = args.git_root if args.git_root not in (None, "", ".") else (args.path or ".")
    info, repo, failure = resolve_git_root(background, root_value)
    if failure:
        failure["operation"] = "git-diff"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    git_args = ["diff", "--no-ext-diff"]
    if args.staged:
        git_args.append("--cached")
    if args.path:
        path_info = resolve_tool_path(background, args.path)
        if not path_info["inside_workspace"]:
            return fail_outside_workspace("git-diff", background, path_info, args.json)
        if not is_relative_to(path_info["path"], repo):
            value = result(False, "git-diff", 5, **git_repo_context(background, repo, info), path=path_info["project_path"], first_failure="Diff path is outside Git repository")
            print_result(value, args.json)
            return 5
        git_args.extend(["--", rel(path_info["path"], repo)])
    diff = run_git_read(repo, git_args, max_bytes=max(1, args.max_bytes), timeout=args.timeout)
    ok = diff["exit_code"] == 0
    value = result(
        ok,
        "git-diff",
        0 if ok else diff["exit_code"],
        **git_repo_context(background, repo, info),
        path=args.path,
        staged=args.staged,
        diff=diff["stdout"],
        stdout_bytes=diff["stdout_bytes"],
        stderr=diff["stderr"],
        truncated=diff["truncated"],
        first_failure=diff["first_failure"],
    )
    print_result(value, args.json)
    return int(value["exit_code"])

def git_log(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info, repo, failure = resolve_git_root(background, args.git_root)
    if failure:
        failure["operation"] = "git-log"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    limit = min(max(1, args.limit), MAX_GIT_LIMIT)
    fmt = "%H%x1f%h%x1f%an%x1f%ae%x1f%ad%x1f%s"
    raw = run_git_read(
        repo,
        ["log", f"-n{limit}", f"--pretty=format:{fmt}", "--date=iso-strict"],
        max_bytes=max(4096, args.max_bytes),
        timeout=args.timeout,
    )
    if not raw["ok"]:
        value = result(False, "git-log", raw["exit_code"], **git_repo_context(background, repo, info), stderr=raw["stderr"], first_failure=raw["first_failure"])
        print_result(value, args.json)
        return int(value["exit_code"])
    commits = []
    for line in raw["stdout"].splitlines():
        parts = line.split("\x1f")
        if len(parts) != 6:
            continue
        commits.append({
            "commit": parts[0],
            "short": parts[1],
            "author": parts[2],
            "email": parts[3],
            "date": parts[4],
            "subject": parts[5],
        })
    value = result(
        True,
        "git-log",
        **git_repo_context(background, repo, info),
        limit=limit,
        commits=commits,
        commit_count=len(commits),
        truncated=raw["truncated"],
    )
    print_result(value, args.json)
    return 0

def git_show(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info, repo, failure = resolve_git_root(background, args.git_root)
    if failure:
        failure["operation"] = "git-show"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    git_args = ["show", "--no-ext-diff", "--decorate=short"]
    if args.stat:
        git_args.append("--stat")
    if args.no_patch:
        git_args.append("--no-patch")
    git_args.append(args.rev)
    shown = run_git_read(repo, git_args, max_bytes=max(1, args.max_bytes), timeout=args.timeout)
    ok = shown["exit_code"] == 0
    value = result(
        ok,
        "git-show",
        0 if ok else shown["exit_code"],
        **git_repo_context(background, repo, info),
        rev=args.rev,
        content=shown["stdout"],
        stdout_bytes=shown["stdout_bytes"],
        stderr=shown["stderr"],
        truncated=shown["truncated"],
        first_failure=shown["first_failure"],
    )
    print_result(value, args.json)
    return int(value["exit_code"])

def git_ls_files(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info, repo, failure = resolve_git_root(background, args.git_root)
    if failure:
        failure["operation"] = "git-ls-files"
        print_result(failure, args.json)
        return int(failure["exit_code"])
    assert repo is not None
    git_args = ["ls-files"]
    if args.glob:
        git_args.extend(["--", args.glob])
    raw = run_git_read(repo, git_args, max_bytes=max(4096, args.max_bytes), timeout=args.timeout)
    if not raw["ok"]:
        value = result(False, "git-ls-files", raw["exit_code"], **git_repo_context(background, repo, info), stderr=raw["stderr"], first_failure=raw["first_failure"])
        print_result(value, args.json)
        return int(value["exit_code"])
    files = [line for line in raw["stdout"].splitlines() if line]
    max_count = max(1, args.max_count)
    value = result(
        True,
        "git-ls-files",
        **git_repo_context(background, repo, info),
        glob=args.glob,
        file_count=len(files),
        files=files[:max_count],
        truncated=len(files) > max_count or raw["truncated"],
    )
    print_result(value, args.json)
    return 0
