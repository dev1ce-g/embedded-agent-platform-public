# Context Intake Field Reference

This is an optional reference for complex embedded changes. Use only the fields
that materially affect scope, safety, implementation, or verification.

## Goal

- Human-readable title.
- Required behavior and observable success.
- Explicit non-goals.
- Delivery constraint or deadline, if relevant.

## Environment

- Product and board revision.
- MCU/SoC/module and active software baseline.
- Bench, vehicle, simulator, unit-test, or production context.
- Toolchain, SDK, compiler, build project, and selected Target.
- Exact repository, branch, Commit, and worktree state.

## Observation

- Actual versus expected behavior.
- First known bad and last known good baseline.
- Reproduction steps and frequency.
- Timeline with each timestamp's source and unit.
- Logs, traces, captures, screenshots, binaries, map/ELF, or schematics.

## Boundaries

- Self-maintained, generated, vendor, third-party, or external-service code.
- MCU/MPU/shared ownership.
- Public API, ABI, protocol, persistence, security, or hardware side effects.
- Concurrency, ISR, task, lifecycle, memory, timing, and power constraints.

## Protocol Detail

When applicable:

- transport and addressing;
- CAN IDs, diagnostic services, DIDs, message direction, and framing;
- byte order, scale, valid range, timeout, retry, and negative response;
- state prerequisites and recovery;
- captured raw evidence.

## Authority

- Outcome owner.
- Allowed write paths.
- Forbidden actions.
- Whether commit/push/CI/flash/reset/CAN transmit/signing/release is authorized.
- Shared device or lab resource ownership.

## Verification

List each claimed layer separately:

- static analysis;
- host/unit test;
- selected Target build;
- artifact freshness and hash;
- CI;
- flash/program/verify;
- observed device or bus behavior.

## Ambiguities

For every unresolved item record:

- the question;
- why it matters;
- current confidence;
- evidence or person needed;
- whether it blocks writes or only a later verification layer.

The user may continue in natural language. The Agent is responsible for
extracting and maintaining this structure only when it adds value.
