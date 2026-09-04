# Embedded Spec Index

This template extends the native Trellis workflow. It does not replace or patch
`.trellis/workflow.md`.

## Core Rules

- `platform-operating-model.md`: host-neutral task ownership and capability
  routing.
- `agent-governance.md`: authority, operation gates, remote execution, and
  evidence requirements.
- `embedded-runtime-workflow.md`: Windows runtime entry and structured tool
  usage.
- `project-discovery.md`: one-time project discovery and profile ownership.
- `project-context.md`: generated project facts and unresolved questions.
- `architecture-boundaries.md`: MCU-only, MCU+MPU, and MCU+SoC boundary gates.
- `soc-integration-boundaries.md`: conditional rules for SoC-side work.
- `repository-layout.md`: source ownership and generated-file boundaries.
- `config-and-generated-files.md`: source-of-truth rules for generated files.
- `safety-and-security.md`: secrets, signing, flash, and irreversible actions.
- `verification.md`: completion evidence and runtime verification.
- `evidence-first-engineering.md`: active-target proof, correction handling,
  proportional design, log timing and layered completion evidence.
- `coding-rules.md`: normative embedded C/C++ coding standard with
  project-style precedence and readability quality gates.
- `third-party-and-sdk-boundary.md`: vendor, SDK, and AUTOSAR boundaries.
- `requirement-intake.md`: routing from natural-language requirements to a
  Trellis task contract.
- `requirement-intake-template.md`: detailed intake form used only when the
  task needs the full embedded requirement path.
- `native-subagent-workflow.md`: read-only evidence-scout routing, delegation
  packets and main-agent verification.
- `git-conventions.md`: Git evidence and repository conventions.

## Architecture Selection

Discovery writes the actual architecture to
`.trellis/spec/project/project-profile.json`. Load only the conditional rules
matching that profile. Template installation must not guess architecture from a
directory name or copy a different runtime for each architecture.

## Ownership

Reusable rules live here. The template ID is retained for compatibility; the
operating model is no longer limited to a dual-machine role split. Project
facts and generated profiles live under
`.trellis/spec/project/`; curated project knowledge lives under
`.trellis/knowledge/project/`; machine Runtime implementations and logs remain
on the host that owns the corresponding capability.
