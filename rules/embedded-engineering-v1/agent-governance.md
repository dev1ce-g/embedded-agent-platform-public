# Agent Governance Rules

These rules apply whenever one or more AI Agents work on an embedded MCU/MPU
project. Read `platform-operating-model.md` first. Host names describe available
capabilities, not permanent Agent roles.

## Authority And Ownership

- Assign one outcome owner for each task. The owner may run on Mac, WSL,
  Windows or another capable host.
- The outcome owner may cover requirement intake, architecture, planning,
  implementation, verification and delivery.
- A delegated Agent owns only the result, workspace and writes stated in its
  task contract. Delegation may include full-project ownership when explicit.
- Review and verification are read-only unless the task contract grants writes.
- Use one writer per workspace. Parallel writers require separate worktrees or
  workspaces.
- Moving work to another host does not grant new authority.

## Required Task Contract

Before writing or delegation begins, record:

- objective, non-goals and acceptance criteria.
- outcome owner and delegated results.
- active repository, workspace, branch and exact Commit.
- allowed write paths and forbidden actions.
- required Engineering Rules, Knowledge and active context.
- required capabilities and selected Adapters.
- expected evidence and handoff location.

Verify missing fields from safe read-only evidence. If an unknown value changes
scope, risk or acceptance, pause for the user instead of inventing it.

## Capability Routing

Keep work on the current host when it has the repository, tools and authority.
Use a remote Agent task when another host should own a substantial result or the
complete project. Use a native subagent only for bounded work inside the current
task. Use a Runtime Job for persistent operations without reasoning.

Windows Native Runtime is the required Adapter for Windows-local embedded
capabilities such as Keil, Jenkins credentials, J-Link, CAN, ADB, SDK and
connected devices. Call its fixed commands and consume structured JSON. Do not
duplicate its quoting, authentication, Gate, polling or evidence logic in the
calling Agent.

If the Runtime cannot express a required operation, record the capability gap.
Adding a new fixed command and tests is the normal platform change. Runtime
failure does not authorize an ad hoc shell, browser Jenkins or direct HTTP path.

## Synchronization

Use Git as the formal synchronization contract between source workspaces:

```text
owner workspace commit -> push/fetch -> target checkout exact SHA -> verify clean
```

Do not overwrite a dirty workspace or use an implicit merging `git pull`.
Targeted copy is acceptable for an explicit deployment or short-lived
verification input, but it does not become the source of truth.

When a project adopts the bundled reference branch policy, validate it with
`embedded-agent-branch check`. Runtime Git mutations must match the exact
current branch and task-approved include paths. Commits, pushes and branch
rewrites require the authority defined by the current task.

## Runtime Interface

The Runtime owns:

- project background and stale checks.
- backend-specific Adapter selection and process architecture.
- fixed command and path validation.
- high-risk Gates and explicit confirmations.
- bounded output, logs, persistent Jobs and artifact metadata.
- structured errors, success markers and evidence.

The Runtime does not own requirements, architecture or final acceptance. The
calling task remains responsible for proving that Runtime evidence satisfies
the project contract.

## High-Risk Gates

Explicit human confirmation is required for:

- firmware flashing and target-changing reset/debug operations.
- eFuse and irreversible security state.
- production keys, certificates and signing policy.
- release, publishing, deployment and production CI parameters.
- destructive deletion outside approved temporary outputs.
- commits, pushes or branch rewrites when not already authorized by the task.

High-risk operations fail closed. Exit code `0` alone is insufficient; verify
the expected marker and relevant log, artifact or hardware evidence. Never copy
private key material, credentials, tokens, cookies or authorization headers
into chat, task files or Git.

Before MCU build or flash, Discovery must enumerate Keil projects and require a
user-selected workspace-relative project path. Directory layout, project name,
output name and sort order are evidence presented to the user, not selection
policy. Persist the selected path in project background and reuse it only while
the project remains a discovered candidate. Distinguish project-level
`.uvprojx` configuration from user-level `.uvoptx` debug configuration and
include both in stale checks when present. Do not let a backend replace the
selected project with a conventional hard-coded path.

## Evidence Standard

For every claimed layer, record the applicable evidence:

- repository, branch, Commit and changed paths.
- command or Runtime operation and exit code.
- first failure or expected success marker.
- log or Job identifier.
- artifact path, size, timestamp and SHA-256.
- target/device identity, probe selector, interface and speed for hardware
  claims.
- separate erase, programming and verify markers for flash; report reset/run
  and observed application behavior as later evidence layers.

Static checks, unit tests, host builds, CI and hardware behavior are separate
claims. Report unverified layers and the reason they remain unverified.
