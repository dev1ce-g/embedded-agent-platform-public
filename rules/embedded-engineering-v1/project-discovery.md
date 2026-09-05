# Project Discovery Rules

Project Discovery is the read-only project-understanding layer between raw
repositories and an Agent's active context.

## Layer Contract

```text
Repository / Manifest / Build Files
        ↓
Raw facts with evidence
        ↓
Generated project and target profiles
        ↓
Project rules and curated knowledge
        ↓
Agent active context
```

Discovery output is evidence, not execution authority.

## Generated Files

Local Discovery writes only generated artifacts to
`.embedded-agent/context/`:

- `discovery-facts.json`
- `project-profile.json`
- `device-profile.json`
- `capability-profile.json`
- `overview.md`
- `module-map.md`
- `build-guide.md`
- `runbooks/index.md`

The Windows Runtime keeps its canonical background in machine-local state:

```text
<runtime-state>\projects\<project-id>\background.json
<runtime-state>\projects\<project-id>\background.md
```

A workspace manifest may connect the project projection to that Runtime
background. Do not copy machine credentials, logs, or device state into the
project context.

## Rules

- Discovery must be parser/script first, bounded, and repeatable.
- It must not build, flash, debug, open a serial stream, transmit CAN, access
  credentials, or trigger CI.
- Ignore generated `.embedded-agent/` content and legacy platform projections
  when scanning source, so refresh does not discover its own output.
- Refresh when source manifests, build projects, SDK selection, toolchain, or
  workspace topology changes; do not rediscover on every model turn.
- Mark facts and capabilities as `detected`, `partial`, or `missing` with
  confidence and evidence.
- `detected` means evidence exists, not that an operation is authorized.
- Low- or medium-confidence facts require confirmation before promotion to a
  project rule or durable knowledge.
- Build, flash, debug, repository mutation, CI, and hardware actions require a
  fixed Capability Contract and the matching Gate.

## Refresh Commands

```bash
embedded-project refresh . --discovery local --json
embedded-project refresh . --discovery local --dry-run --json
```

For a canonical Windows workspace:

```bash
embedded-agent project discover \
  --project <id> \
  --workspace <win-path> \
  --json

embedded-agent project discover \
  --project <id> \
  --workspace <win-path> \
  --keil-project <workspace-relative-uvprojx> \
  --write-background \
  --json
```

The Windows workspace must be contained by the machine-configured
`EMBEDDED_AGENT_WORKSPACE_ROOT`; requests cannot widen that boundary.

If more than one build project is plausible, return candidates and require an
explicit selection. Directory names, timestamps, or sort order are never target
selection policy.
