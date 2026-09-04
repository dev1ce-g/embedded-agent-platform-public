---
name: embedded-can-runtime
description: Operate the Embedded Agent Platform CAN Runtime for driver inventory and preflight, bounded CAN monitoring, confirmed frame transmission, and bounded UDS ECU or tester sessions. Use when a task mentions ControlCAN, ZCANPro, USB-CAN, CAN frames, bus monitoring, CAN IDs, bitrate, UDS requests, or CAN driver readiness on the managed Windows host.
---

# Embedded CAN Runtime

Treat the CAN bus as shared external state. Use the platform Runtime as the only execution surface.

## Workflow

1. Read the nearest project `AGENTS.md`, `.trellis/workflow.md`, and the Runtime and hardware-operation Specs.
2. Resolve the project ID and confirm its Windows background with `project show` and `project check-stale` when the operation depends on a project workspace.
3. Classify the action:
   - Inventory: `driver-list`, `driver-probe`, `device-probe`, `self-test`, `check-env`.
   - Observe: `monitor`.
   - Mutate: `send`, `uds-ecu`, `uds-tester`.
4. For a hardware action, name the driver, channel, bitrate, device index and any vendor-specific selector. Present multiple plausible adapters as candidates; preserve the user's explicit choice.
5. Run inventory before opening hardware. Require `ready: true` and inspect blockers, DLL architecture and Python adapter evidence.
6. Bound every observation by `--duration` or `--count`. Bound an ECU simulation by `--idle-timeout` or `--max-requests`.
7. Before a mutate action, show the exact frames or UDS request set and obtain the project L3 confirmation. Pass both `--require-confirm` and `--confirm` only after that gate is satisfied.
8. Return the Runtime JSON evidence, including driver, channel, bitrate, limits, frame counts, first failure and remaining hardware-validation status.

## Command surface

Use only `embedded-agent can ... --json`. Read [references/runtime-contract.md](references/runtime-contract.md) for the fixed commands and current capability limits.

## Hard gates

- Keep driver selection explicit when more than one adapter is plausible.
- Treat a single detected adapter as evidence, not authorization to persist or use it.
- Keep monitor and UDS server operations finite.
- Keep CAN transmit and UDS activity behind the L3 confirmation gate.
- Use `driver-list`, `driver-probe` and `self-test` without opening hardware. Use bounded `device-probe` only when the physical selector is unknown; it may open and immediately close candidates but never initializes a channel or transmits.
- Report a missing Runtime command as a capability gap. Keep vendor DLL calls and ad hoc Python CAN scripts outside project tasks.

## Completion criteria

Complete only when the result identifies the Runtime contract, selected driver and channel, bitrate, operation bound, confirmation state for mutations, structured result and first failure, plus whether physical-bus behavior was actually observed.

Read [references/provenance.md](references/provenance.md) when changing this Skill from upstream ideas.
