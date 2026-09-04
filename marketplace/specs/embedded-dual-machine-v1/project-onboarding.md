# Embedded Project Onboarding

This protocol is idempotent and host-neutral. Initialize a project once. Normal
tasks reuse its Trellis projection and refresh only facts that became stale.

## First-Time Entry

Before entering an embedded project, verify:

1. The repository root, current branch/Commit and worktree status.
2. The nearest `AGENTS.md`, `.trellis/workflow.md` and embedded Spec.
3. A stable project ID and generated project profile.
4. The active build targets and required host/tool/device capabilities.
5. One outcome owner and one writer for each workspace.

Use the local bootstrap when the current host owns the canonical repository:

```bash
trellis-embedded-init <project-path> \
  --project-id <project-id> \
  --discovery local \
  --build-knowledge \
  --json
```

The bootstrap initializes Trellis, installs the embedded Spec and performs
read-only Discovery. It does not build, flash, reset, access devices or change
credentials.

Register a Windows workspace only when the project requires Windows Runtime
capabilities:

```bash
trellis-embedded-init <project-path> \
  --project-id <project-id> \
  --windows-agent-workspace 'C:\\Workspaces\\<project-id>\\workspace' \
  --sync-mode git \
  --build-knowledge \
  --json
```

The legacy `--windows-workspace` option remains an alias. A Windows/WSL Codex
task that owns the complete project may use its own canonical workspace; the
term `agent-workspace` does not imply an execution-only role.

## Project State

Generated project facts live under `.trellis/spec/project/` and
`.trellis/knowledge/project/`. A workspace manifest records repositories,
remotes, branches and exact Commit SHAs when multiple workspaces participate.
Generated state remains outside product Git unless the project explicitly
versions a stable profile.

For an initialized project, load the existing profile and task context. Run
Windows Runtime `project show` and `project check-stale` only when using a
registered Windows capability Adapter. Do not force Windows availability for
local architecture, implementation or tests that do not need it.

## Workspace And Synchronization

Use one writer per workspace. A project may keep separate human and Agent
workspaces, or allow an authorized Agent to own the canonical project
workspace. The task contract must state which model applies.

When source crosses workspaces, use:

```text
owner workspace commit
  -> push/fetch
  -> target workspace checkout exact Commit SHA
  -> verify clean
```

Do not use an implicit merging `git pull`, recursive source copy, automatic
merge or automatic reset as the formal synchronization path. A dirty or
divergent workspace is a blocking state.

## Per-Task Entry

Before editing:

1. Confirm objective, owner, allowed writes and acceptance evidence.
2. Prove the active target and relevant call chain.
3. Load only the matching Spec and Knowledge.
4. Select local or remote Adapters for missing capabilities.
5. Validate the task branch according to `git-conventions.md`.

Changing host does not restart onboarding. Continue the same Trellis task and
Context Packet, preserving decisions and invalidated assumptions.

## Failure Rules

Stop and report when:

- the canonical workspace or required capability is missing.
- a workspace has unknown modifications or diverges from the expected Commit.
- a required repository Commit cannot be fetched.
- the project ID resolves to another workspace.
- task ownership, write scope or high-risk authority is unknown.

Resolve these states explicitly. Do not repair them with broad copy, reset,
cleanup, credential access or browser fallbacks.
