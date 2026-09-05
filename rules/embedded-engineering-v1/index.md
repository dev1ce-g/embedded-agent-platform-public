# Embedded Engineering Rule Index

This Rule Pack provides project context, safety boundaries, and evidence
requirements for embedded engineering Agents. It does not prescribe a model,
prompt chain, task store, or mandatory workflow.

## Core Rules

- `platform-operating-model.md`: host-neutral ownership and capability routing.
- `agent-governance.md`: authority, operation gates, delegation, and evidence.
- `project-onboarding.md`: project entry and stale-context handling.
- `project-discovery.md`: parser-first project and target fact generation.
- `project-context.md`: facts worth maintaining for an active project.
- `architecture-boundaries.md`: MCU-only, MCU+MPU, and MCU+SoC boundaries.
- `soc-integration-boundaries.md`: conditional rules for SoC-side work.
- `repository-layout.md`: source ownership and generated-file boundaries.
- `config-and-generated-files.md`: source-of-truth rules for generated files.
- `safety-and-security.md`: secrets, signing, flash, and irreversible actions.
- `evidence-first-engineering.md`: active-target proof and layered evidence.
- `verification.md`: completion and verification requirements.
- `coding-rules.md`: embedded C/C++ engineering and readability rules.
- `third-party-and-sdk-boundary.md`: vendor, SDK, and generated-code ownership.
- `git-conventions.md`: Git evidence and safe synchronization.
- `windows-runtime-capabilities.md`: fixed Windows Runtime command surface.
- `jenkins-capabilities.md`: bounded CI inspection, trigger, and evidence.

## Optional Guides

- `guides/context-intake.md`: compile natural-language requirements into a
  concise task context when scope or risk warrants it.
- `guides/context-intake-template.md`: optional fields for complex tasks.
- `guides/agent-delegation.md`: bounded, model-independent delegation.

Discovery writes generated facts to `.embedded-agent/context/`. Project-owned
rules live under `.embedded-agent/rules/project/`; curated knowledge lives
under `.embedded-agent/knowledge/` or existing project documentation.

Generated facts are evidence, not execution authority. Build, CI, repository,
flash, debug, CAN transmit, reset, signing, and production actions still require
the matching Capability Contract and Gate.
