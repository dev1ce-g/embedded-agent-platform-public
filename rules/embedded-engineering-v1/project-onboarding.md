# Embedded Project Onboarding

Project onboarding is idempotent and model-independent. Initialize once, then
refresh only generated facts that became stale.

## First-Time Entry

```bash
embedded-project init <project-path> --discovery local --json
embedded-project doctor <project-path> --json
```

Before changing source, confirm:

1. repository root, worktree state, branch, and exact Commit;
2. nearest `AGENTS.md`, platform rules, applicable project rules, and knowledge;
3. generated project profile and unresolved low-confidence facts;
4. active build Target and required host/tool/device capabilities;
5. one outcome owner and one writer for each workspace;
6. allowed writes, forbidden actions, and acceptance evidence.

Bootstrap installs rules and runs read-only Discovery. It never builds, flashes,
resets, operates a device, triggers CI, or reads credentials.

## Windows-Backed Project

Register a Windows workspace only when required capabilities exist there:

```bash
embedded-project init <project-path> \
  --project-id <project-id> \
  --windows-workspace 'C:\\Workspaces\\<project-id>' \
  --build-knowledge \
  --json
```

The generated `.embedded-agent/context/workspace-manifest.json` records
repositories, remotes, branches, and exact Commit SHAs. Windows Runtime
Background remains machine-local.

## Project State

- `.embedded-agent/context/` contains replaceable generated facts.
- `.embedded-agent/rules/platform/` contains platform-managed rules.
- `.embedded-agent/rules/project/` contains project-owned constraints.
- `.embedded-agent/knowledge/` or existing docs contain durable project
  knowledge.

Load only the material relevant to the current task. Run Windows Runtime
`project show` and `project check-stale` only when that Runtime is selected.

## Workspace And Synchronization

Use one writer per workspace. When source crosses workspaces:

```text
owner workspace commit
  -> push/fetch
  -> target workspace checkout exact Commit SHA
  -> verify clean
```

Do not use implicit merging `git pull`, recursive copy, automatic merge, or
automatic reset as the formal synchronization path.

## Per-Task Entry

A task may be handled directly or with an optional structured context. Before
writing:

1. establish objective, owner, write scope, forbidden actions, and acceptance;
2. prove the active Target and relevant call chain;
3. load only matching rules, generated facts, and knowledge;
4. select local or remote Adapters for missing capabilities;
5. preserve corrections and invalidate superseded assumptions.

Changing host does not restart the work. Carry forward the same goal, decisions,
source SHA, permissions, and evidence references without requiring a platform
task store or workflow.

## Failure Rules

Stop and report when the canonical workspace, required capability, Target proof,
write authority, or acceptance evidence is unknown. Do not resolve these states
with broad copy, reset, cleanup, credential access, or unbounded shell fallbacks.
