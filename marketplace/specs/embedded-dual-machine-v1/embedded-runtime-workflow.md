# Embedded Runtime Workflow

This spec defines the entry flow for tasks that need Windows Runtime
capabilities. It complements the host-neutral Trellis workflow and does not
assign planning or project ownership to a specific host.

`embedded-agent` is a machine-level client/runtime contract. Do not assume a
project-local `.trellis/agents/` copy exists or use one as the update source.

## Scope

This page covers only routine runtime entry rules:

- project background check.
- Windows `embedded-agent tool ...` usage for read/search/list/log inspection.
- Windows `embedded-agent git ...` usage for read-only Git inspection.
- Windows `embedded-agent device ...` usage for bounded, read-only ADB
  inspection.
- build environment and build evidence expectations.

Hardware-changing operations such as flash, reset-mode capture, eFuse,
production signing, destructive cleanup or board-farm control are intentionally
out of scope here. Use `.trellis/spec/agent-governance.md` for those gates.

## 1. Project Background Check

Before doing embedded project work through the Windows runtime, identify the
project id and confirm that Windows already has a background snapshot:

```bash
embedded-agent project show --project <project-id> --json
embedded-agent project check-stale --project <project-id> --json
```

If no background exists, register it once from the Windows workspace:

```bash
embedded-agent project discover \
  --project <project-id> \
  --workspace <windows-workspace-path> \
  --json
```

If Discovery reports `selection_required`, ask the user to select one item from
`selection_candidates`, then persist the background:

```bash
embedded-agent project discover \
  --project <project-id> \
  --workspace <windows-workspace-path> \
  --keil-project <workspace-relative-uvprojx> \
  --write-background \
  --json
```

Rules:

- Project background is stable task context. Do not rediscover it on every AI
  turn.
- Do not infer the MCU Keil project from organization-specific directory conventions, names
  or sort order. The selected relative path is a user decision.
- Refresh background only when manifest, Keil project, build wrapper, workspace
  path or major repository layout changes.
- Use returned `project_id`, `background_id`, `workspace`, `architecture` and
  `targets` as the runtime source of truth.
- If `check-stale` reports stale, refresh discovery before relying on build or
  toolchain facts.

## 2. Windows Tool Proxy

For Windows-side file inspection, prefer the local `embedded-agent` tool proxy
instead of ad hoc `ssh powershell ...` commands:

```bash
embedded-agent tool resolve-path --project <project-id> --path <path> --json
embedded-agent tool stat --project <project-id> --path <path> --json
embedded-agent tool list --project <project-id> --path <path> --json
embedded-agent tool find --project <project-id> --root <path> --glob <glob> --json
embedded-agent tool rg --project <project-id> --pattern <text> --root <path> --glob <glob> --json
embedded-agent tool read --project <project-id> --path <path> --max-bytes <n> --json
embedded-agent tool tail --project <project-id> --path <path> --lines <n> --json
embedded-agent tool first-failure --project <project-id> --path <path> --json
```

Rules:

- Treat `embedded-agent tool ...` as the default path for Windows project
  search, read, list, stat and bounded log inspection.
- Avoid hand-written PowerShell pipelines for common operations such as `rg`,
  `Get-Content`, `Select-String`, directory listing or log tailing.
- Tool output must stay bounded. Prefer counts, short snippets, `truncated`
  flags and normalized paths over large raw logs.
- Tool reads are project-workspace scoped by default. A path outside the
  discovered workspace should fail closed instead of being read silently.
- If a direct SSH command is unavoidable, keep it read-only and record why the
  tool proxy was insufficient.

## 3. Read-Only Device Inspection

For connected-board inventory and serial-device ownership evidence, prefer the
fixed Windows runtime commands:

```bash
embedded-agent device list --project <project-id> --json
embedded-agent device serial-inspect \
  --project <project-id> \
  --tty <tty-name> \
  --json
```

If more than one ADB device is online, pass the exact serial returned by
`device list` through `--serial`.

Rules:

- `serial-inspect` may read only the named `/dev/tty*` node metadata, its sysfs
  driver/uevent data and process file-descriptor links.
- It must not read the TTY payload because doing so can consume live protocol
  data from the owning application.
- It must not expose arbitrary ADB shell arguments, write device files, change
  permissions, restart services or reboot the board.
- Device-changing operations remain behind their dedicated high-risk gate.

## 4. Git Inspection And Controlled Branch Attachment

For Windows-side Git state, prefer the local `embedded-agent git ...` wrapper
instead of ad hoc `ssh powershell git ...` commands:

```bash
embedded-agent git root --project <project-id> --root <path> --json
embedded-agent git status --project <project-id> --root <path> --json
embedded-agent git diff-summary --project <project-id> --root <path> --json
embedded-agent git diff --project <project-id> --path <path> --max-bytes <n> --json
embedded-agent git log --project <project-id> --limit 20 --json
embedded-agent git show --project <project-id> --rev HEAD --stat --no-patch --json
embedded-agent git ls-files --project <project-id> --glob <glob> --json
embedded-agent git switch \
  --project <project-id> \
  --path <repo-path> \
  --branch <task-branch> \
  --commit <full-sha> \
  --confirm \
  --json
embedded-agent git create-branch \
  --project <project-id> \
  --path <repo-path> \
  --branch <new-task-branch> \
  --commit <current-full-sha> \
  --confirm \
  --json
embedded-agent git commit \
  --project <project-id> \
  --path <repo-path> \
  --branch <task-branch> \
  --message <single-line-message> \
  --include <approved-repo-path> \
  --confirm \
  --json
```

Rules:

- Git evidence commands are read-only. Use them for status, diff, recent
  history and tracked-file discovery in the Windows workspace.
- Do not pass arbitrary `git` arguments through SSH. Use the fixed wrapper
  commands so quoting, pager behavior, encoding, timeout and output bounds stay
  controlled by the Windows runtime agent.
- Git roots and file paths must remain inside the discovered project workspace.
- Large diff/show output must stay bounded through `--max-bytes` and
  `truncated`.
- `git switch` is the controlled existing-branch attachment operation. It requires
  a clean repository, exact remote task branch, full Commit SHA and explicit
  confirmation. It must refuse a divergent existing local branch and must not
  reset, merge, rebase, commit or push.
- `git create-branch` may preserve a reviewed dirty worktree only when current
  `HEAD` matches the supplied full SHA. It rejects existing branches and
  unmerged entries, then proves the worktree status did not change.
- `git commit` may stage and commit only explicit repository-relative include
  paths on the named current branch. It refuses pre-staged changes and verifies
  the staged allowlist before committing.
- Arbitrary checkout, reset, clean, pull, merge, rebase and push remain outside
  the wrapper.

## 5. Build Environment And Evidence

Build is a verification action. It does not modify the connected board and does
not require a hardware-operation gate.

Use the Windows Runtime when the selected build environment is Windows-local:

```bash
embedded-agent build --project <project-id> --target keil --json
embedded-agent build --project <project-id> --target mpu --json
```

Rules:

- Run the build on any host with a verified compatible toolchain. Use Windows
  Runtime when the project or task selects the Windows build environment.
- Build commands should resolve workspace, toolchain, Keil project, Docker SDK
  and target details from Windows project background.
- Build does not need the flash/board gate, but it still needs stable
  environment evidence.
- A build success claim should include:
  - wrapper command.
  - `project_id` and `background_id`.
  - target (`keil` or `mpu`; `mcu` remains a compatibility alias for Keil).
  - exit code.
  - log path.
  - success marker or first failure.
  - artifact path, size, mtime and SHA256 when an artifact is produced.
- If build fails, inspect the first failure through the Windows tool proxy or
  returned backend evidence before editing code.

## 6. Persistent Runtime Jobs

Use a persistent Runtime Job when a controlled build or Jenkins wait may outlive
the current SSH connection or model turn:

```bash
embedded-agent job start \
  --project <project-id> \
  --kind build \
  --target keil \
  --json

embedded-agent job start \
  --project <project-id> \
  --kind jenkins-wait \
  --job <jenkins-job> \
  --build <build-number> \
  --json
```

Keep the returned `job_id` in the task Context Packet, then inspect only new
output:

```bash
embedded-agent job status --job-id <job-id> --json
embedded-agent job output --job-id <job-id> --stream stdout --offset <offset> --json
embedded-agent job list --project <project-id> --json
embedded-agent job cancel --job-id <job-id> --confirm --json
```

Rules:

- Jobs are durable Runtime evidence, not additional planning Agents.
- Only fixed operation kinds published by `embedded-agent` may be started. Do
  not add an arbitrary shell or command pass-through.
- Background and stale checks happen before a build Job starts. An equivalent
  active operation is rejected instead of launched twice.
- Consume `next_offset` from `job output`; do not repeatedly reload full logs
  into model context.
- A terminal `succeeded` state still requires inspection of structured result
  and expected build/Jenkins evidence before claiming task completion.
- Cancel requires `--confirm` and terminates only the process tree owned by that
  Job. Device operations remain outside this command surface.

## 7. CAN Runtime Module

Use the fixed CAN command surface instead of importing vendor DLLs from task
scripts:

```bash
embedded-agent can driver-list --json
embedded-agent can driver-probe --driver controlcan --json
embedded-agent can device-probe --driver <controlcan|zcanpro> --json
embedded-agent can self-test --json
embedded-agent can monitor --driver controlcan --duration 10 --json
embedded-agent can send --driver controlcan --frame 0x123#01020304 --require-confirm --confirm --json
```

Rules:

- ControlCAN and ZCANPro are Driver Adapters behind one CAN Runtime Interface.
- Driver listing, preflight and self-test must not open hardware. A bounded device probe may only open and immediately close fixed candidates; it must not initialize a channel or transmit.
- Monitoring must have a duration or frame-count bound.
- Send, replay and UDS operations require the L3 confirmation gate.
- DLL architecture, Python packages and vendor library paths belong to the
  Adapter implementation and must not leak into project task scripts.

## Relationship To Other Specs

- `.trellis/spec/agent-governance.md`: authority boundaries, high-risk gates
  and evidence standard.
- `.trellis/spec/evidence-first-engineering.md`: active-target proof, log timing
  protocol and layered completion claims.
- `.trellis/spec/project-discovery.md`: discovery and generated profile rules.
- `.trellis/spec/verification.md`: completion and validation expectations.
- `.trellis/spec/native-subagent-workflow.md`: read-only Scout delegation and
  context-return rules.
- `.trellis/spec/platform-operating-model.md`: host-neutral ownership and
  capability routing.
- `.trellis/knowledge/architecture/dual-machine-agent-system.md`: optional
  multi-host topology and Runtime Adapter notes.
