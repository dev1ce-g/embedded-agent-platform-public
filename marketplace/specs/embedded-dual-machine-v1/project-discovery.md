# Project Discovery Rules

Project Discovery is the embedded project-understanding layer that sits below
Trellis task workflow and above raw repository files.

The task owner selects the discovery Adapter. Local discovery owns repository
facts when the current host has the canonical workspace. Windows
`embedded-agent` owns Windows toolchain and device-capability facts when those
capabilities are required.

## Layer Contract

Use this model:

```text
Repository / Manifest / Build Files
        ↓
Raw Facts
        ↓
Generated Profiles
        ↓
Human Knowledge
        ↓
Task Context / Embedded Agent Capability
```

Discovery output is evidence, not execution authority.

## Generated Files

A machine-level discovery tool or the bootstrap's local fallback writes
generated artifacts to:

- `.trellis/spec/project/discovery-facts.json`
- `.trellis/spec/project/project-profile.json`
- `.trellis/spec/project/device-profile.json`
- `.trellis/spec/project/capability-profile.json`
- `.trellis/spec/project/*.md`
- `.trellis/knowledge/project/*.md`

The JSON files are preferred by agents. The Markdown files are for human review
and task planning.

The Windows local embedded-agent writes the canonical runtime background to:

```text
<runtime-state>\projects\<project-id>\background.json
<runtime-state>\projects\<project-id>\background.md
```

Mirror this into `.trellis/spec/project/` only when another workspace needs a
reviewable project profile.

## Rules

- Discovery must be parser/script first and repeatable.
- Discovery must not execute build, flash, debug, serial, ADB, CAN or SSH
  commands.
- Project background should be discovered once and refreshed explicitly when
  stale, not rediscovered for every task.
- Discovery may mark a capability as `detected`, `partial` or `missing`.
- `detected` means evidence exists, not that an agent may execute it.
- Build, flash, debug and hardware-adjacent actions still require a Trellis
  task, allowed write paths, stable wrapper command and evidence contract.
- Low or medium confidence generated facts must be reviewed before they are
  copied into hand-written `.trellis/spec/` rules.

## Refresh Commands

```bash
trellis-embedded-init . --skip-trellis-init --discovery local --json
```

Use `--dry-run` before writing when evaluating a new workspace:

```bash
trellis-embedded-init . --skip-trellis-init --discovery local --dry-run --json
```

For the canonical Windows workspace, refresh through the runtime instead:

```bash
embedded-agent project discover --project <id> --workspace <win-path> --json

# Ask the user to select one path from selection_candidates, then persist it.
embedded-agent project discover --project <id> --workspace <win-path> \
  --keil-project <workspace-relative-uvprojx> --write-background --json
```
