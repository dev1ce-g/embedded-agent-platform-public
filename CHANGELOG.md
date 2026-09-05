# Changelog

This file records user-visible platform changes. Platform, Capability Contract,
and individual schema versions are independent version axes.

## [0.2.0] - Unreleased

`0.2.0` is a release candidate until its release commit, CI run, and tag exist.
It intentionally breaks the active Trellis-based architecture from `0.1.0`
instead of maintaining two execution models.

### Added

- Model-independent `.embedded-agent/` project projection for generated
  context, platform and project rules, durable knowledge, and local evidence.
- `embedded-project init`, `refresh`, `doctor`, and explicit
  `migrate-trellis` commands.
- Versioned Embedded Engineering Rule Pack under `rules/`.
- Capability Contract v1 schemas and a common Runtime result envelope.
- Typed persistent Job request v2 with pinned project and connection identity.
- Machine-owned Jenkins, Aboot, and CAN connection registries.

### Changed

- The model owns reasoning and orchestration; the platform owns facts, bounded
  capabilities, safety gates, durable execution state, and evidence.
- `trellis-embedded-init` becomes `embedded-project`.
- `trellis-branch` becomes `embedded-agent-branch`.
- The public rule source moves from
  `marketplace/specs/embedded-dual-machine-v1/` to
  `rules/embedded-engineering-v1/`.
- Mac and WSL adapters are transport-only and cannot override Windows
  launcher-owned Runtime roots or backends.
- Jenkins, Aboot, and CAN callers select a machine-owned connection ID instead
  of supplying endpoint, executable, firmware-root, or vendor-library paths.
- RTT capture with reset requires both `--require-confirm` and `--confirm`.

### Removed

- Active Trellis imports, CLI calls, project workflows, tasks, hooks, agents,
  and Runtime session assumptions.
- The model-specific Windows `claude-start.py` launcher.
- Caller-selected `knowledge export --to` and `workspace remove` surfaces.
- Caller-selected SDK workspace/root overrides and arbitrary Job commands.

### Security

- Constrain registered workspaces and generated artifacts to canonical roots,
  including symlink and Windows reparse-point checks.
- Pin Jenkins requests, redirects, and artifacts to the configured origin.
- Pin Aboot tools and firmware roots with a mandatory tool hash; pin CAN DLLs
  to the machine registry, canonical non-reparse paths, and optional hashes.
- Revalidate queued-job identity and project workspaces when jobs are read or
  executed.
- Restrict MPU container reuse by mount, namespace, capability, device, and
  Docker-socket policy.

### Migration

- Migration is one-way and non-destructive. It imports project-owned context,
  knowledge, and rules without activating old workflows or deleting
  `.trellis/`.
- See [the `0.1` to `0.2` upgrade guide](docs/migration/0.1-to-0.2.md) and the
  [project-data mapping](docs/migration/from-trellis.md).

### Known limitations

- Capability Catalog, persisted Preflight/input binding, scoped Approval, and
  terminal Receipt handlers are specified but not implemented.
- The Runtime-facing SDK commands assume a separately managed SDK store; this
  repository does not yet publish the SDK Manager.
- The open simulator/board execution Golden Path and adapter conformance kit
  remain planned.
- Release acceptance currently covers software-only tests. It does not claim a
  real Windows toolchain build, Docker build, Jenkins service, signing, flash,
  CAN device, RTT probe, or hardware test.

### Version matrix

| Surface | Version |
| --- | --- |
| Platform release candidate | `0.2.0` |
| Capability Contract | `1.0.0` |
| Persistent Job request schema | `embedded-runtime-job-request/v2` |

The current acceptance record is in
[`docs/releases/0.2.0.md`](docs/releases/0.2.0.md).

[0.2.0]: docs/releases/0.2.0.md
