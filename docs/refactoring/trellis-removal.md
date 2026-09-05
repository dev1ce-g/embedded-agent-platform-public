# Trellis Removal And Platform Refactoring

## Objective

Turn the repository from a Trellis-based development preset into a
model-independent context and controlled-capability plane for brownfield
embedded engineering.

The refactor preserves the valuable assets—engineering rules, project
discovery, Windows tool adapters, gates, jobs, and evidence—while removing the
workflow engine, task-store, and model-launcher assumptions.

## Architecture Decision

```text
Any Agent
  -> .embedded-agent rules / context / knowledge
  -> Capability Contract v1
  -> Local / Windows / WSL / CI / Debug / Device Adapters
```

The model owns reasoning. The platform owns facts, capability boundaries,
external side effects, and evidence.

## Work Packages

| Phase | Scope | Exit condition | Status |
| --- | --- | --- | --- |
| 0 | Freeze ownership and projection model | `.embedded-agent/` paths and model-independent terminology agreed | Implemented |
| 1 | Remove active Trellis dependency | Init, refresh, doctor, Discovery, rules, and Runtime work with no Trellis executable or directory | Implemented |
| 2 | Preserve knowledge safely | Explicit non-destructive migration; project rules/knowledge remain project-owned | Implemented |
| 3a | Capability boundary foundation | Versioned result/request schemas, stable result envelope, typed Jobs, reset/write gates | Implemented |
| 3b | Stateful capability lifecycle | Runtime catalog, persisted preflight/input binding, scoped approval and terminal receipt handlers | Planned |
| 4 | Public software Golden Path | Fresh project → init → doctor → refresh → doctor; deterministic context, repeatable in CI | Implemented |
| 5 | Open execution Golden Path | Open toolchain or simulator → build → artifact receipt → run/flash → bounded observation | Planned |
| 6 | Adapter ecosystem | Adapter manifest, published SDK Manager, fake target, conformance tests, MCP thin adapter | Planned |
| 7 | Lab backends | Evaluate Jumpstarter/PlatformIO/OpenOCD/Renode behind the same contract | Planned |

The `0.2.0` release boundary ends at Phase 4. Planned phases are separate,
reviewable increments and are not blockers for this release candidate. See the
[changelog](../../CHANGELOG.md), [upgrade guide](../migration/0.1-to-0.2.md),
and [acceptance record](../releases/0.2.0.md).

## Breaking Changes

- `trellis-embedded-init` is replaced by `embedded-project`.
- `trellis-branch` is replaced by `embedded-agent-branch`.
- `marketplace/specs/embedded-dual-machine-v1` becomes
  `rules/embedded-engineering-v1`.
- Project state moves from `.trellis/` to `.embedded-agent/`.
- The model-specific Windows Claude launcher is removed.
- The unbounded host-path `knowledge export --to` surface is removed; use
  `knowledge build --write` and `knowledge show` until the stateful lifecycle
  provides a typed artifact export.
- Runtime Capability Contract moves to major version 1.

Because the public repository was at `0.1.x`, this refactor intentionally
chooses a clean model instead of maintaining two active architectures.

## Compatibility Policy

Compatibility is data migration, not dual execution:

- old content is read only by `embedded-project migrate-trellis`;
- migration never calls the old CLI and never deletes the source;
- old tasks/workflows/hooks are reported but not activated;
- project-owned knowledge and custom rules are copied conflict-safely;
- migration itself skips Discovery; run `init` or `refresh`, then `doctor`, to
  regenerate facts and validate the projection;
- no bidirectional synchronization is provided.

## Verification

Release acceptance requires:

1. no active code path imports, invokes, or requires Trellis;
2. fresh initialization succeeds with no `.trellis/` and no Trellis executable;
3. no workflow/task directories are generated;
4. repeat init/refresh is idempotent and conflicts do not overwrite user files;
5. project-owned `rules/project/` and `knowledge/` are not globally excluded;
6. Runtime result envelopes identify Capability Contract v1; lifecycle schemas
   not yet wired to handlers remain explicitly marked as planned;
7. reset and other external-state mutations fail closed without confirmation;
8. Bootstrap and Runtime default test suites pass on supported CI hosts;
9. remaining occurrences of the old name are limited to the explicit migration
   surface, defensive exclusion/diagnostics, legacy cleanup, regression tests,
   and migration-facing documentation.

## Next Implementation Slice

The next release should add a fully open execution example using a simulator or
widely available board. It should prove:

```text
discover
  -> preflight
  -> build
  -> artifact hash
  -> run or confirmed flash
  -> bounded log capture
  -> assertion
  -> evidence bundle
```

That example should use the same Runtime Core and Contract as private Windows,
Keil, J-Link, CAN, and Jenkins adapters. It must not add a second execution
engine or a model-specific workflow.

Phase 3b must also turn currently documented trust assumptions into explicit
Preflight evidence: machine-owned executable identity, Keil hook/output review,
and MPU container isolation (no unrelated writable mounts, Docker socket,
privileged mode, host namespaces, devices, or added capabilities).
