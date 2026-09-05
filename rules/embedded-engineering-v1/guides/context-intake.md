# Optional Context Intake Guide

Use this guide when a natural-language request spans multiple modules, hardware
boundaries, protocols, safety constraints, or hosts. A small, explicit change
does not need a ceremony or generated document.

The Agent performs the structuring. Do not ask the user to fill out a form or
expose model reasoning.

## Information To Establish

Prioritize facts that can change scope or safety:

1. target product, hardware revision, software baseline, and reproduction
   environment;
2. observed behavior, expected behavior, and timeline;
3. active MCU/SoC/module ownership and self-maintained versus vendor boundaries;
4. protocol details such as CAN IDs, service IDs, byte order, timeout, and
   response semantics;
5. allowed writes, forbidden operations, and required verification;
6. relevant logs, captures, schematics, topology, sequence, or CI artifacts.

Ask no more than five focused questions at once. Continue safe read-only
discovery while non-blocking facts remain unknown.

## Fact Quality

Classify each material item:

- `high`: explicitly provided or proven by source/build/runtime evidence;
- `medium`: supported inference that still needs confirmation;
- `low`: hypothesis or missing evidence.

Do not use medium/low ownership, Target, protocol, or safety assumptions to
authorize implementation or hardware operations.

## Optional Portable Context

When a cross-host handoff or long-running change needs persistence, the Agent may
emit a compact context document at a user-approved location. The platform does
not require or manage its lifecycle.

```yaml
schema_version: embedded-active-context/v1
objective:
non_goals: []
source:
  repository:
  workspace:
  branch:
  commit:
target:
  id:
  evidence: []
boundaries:
  - statement:
    confidence: high
    source:
ownership: {}
constraints: []
allowed_writes: []
forbidden_actions: []
capabilities: []
acceptance: []
ambiguities: []
evidence_refs: []
```

Keep facts, inference, decisions, and unresolved questions distinct. When new
evidence invalidates an item, mark or replace it before implementation
continues.

## Output Boundary

Context compilation may help an Agent reason and hand off work, but it does not
create a workflow, grant permissions, select a Target, or prove completion.
Runtime receipts and project evidence remain authoritative for actual
operations.
