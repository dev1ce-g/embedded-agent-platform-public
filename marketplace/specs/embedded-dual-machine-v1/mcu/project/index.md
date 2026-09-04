# MCU Project Spec

This package layer is a Trellis routing shim for MCU tasks. The authoritative
rules are the project-level specs in `.trellis/spec/*.md`.

## Context Manifest Rule

`get_context.py --mode packages` lists this routing shim, but it does not
auto-inject the flat project specs or `.trellis/knowledge/` files. During
workflow Phase 1.3, add the applicable files explicitly to `implement.jsonl` and
`check.jsonl`; do not assume this index file alone gives a sub-agent enough
context.

## Pre-Development Checklist

- Read `.trellis/spec/project-context.md`.
- Read `.trellis/spec/repository-layout.md`.
- Read `.trellis/spec/architecture-boundaries.md`.
- Read `.trellis/spec/architecture-boundaries.md` for cross-CPU behavior.
- Read `.trellis/spec/guides/index.md` when the task crosses MCU/MPU,
  generated config, storage, ISR/task or repeated-pattern boundaries.
- Read `.trellis/spec/config-and-generated-files.md` before changing
  `mcu/project/config/` or MDK project files.
- Read `.trellis/spec/evidence-first-engineering.md` before choosing among
  multiple targets, analyzing timing logs or generalizing a design.
- Read `.trellis/spec/third-party-and-sdk-boundary.md` before touching SDK,
  AUTOSAR or third-party code.
- Add matching project knowledge only when it exists and the task touches that
  subsystem; do not assume a generic template supplied product-specific facts.

## Quality Check

- Confirm MCU target ambiguity was handled when touching platform-specific code.
- Confirm any new source file is included in the MDK project.
- Confirm cross-CPU contracts were checked when relevant.
- Confirm validation is reported per `.trellis/spec/verification.md`.
