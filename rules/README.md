# Engineering Rule Packs

This directory is the model-independent source catalog for reusable embedded
engineering rules. The bundled pack is:

- `embedded-engineering-v1/`: brownfield project discovery, target proof,
  ownership, safety gates, controlled Runtime usage, and layered evidence.

`embedded-project init` projects the selected pack into
`.embedded-agent/rules/platform/`. Platform-managed files are updated
idempotently; conflicting local edits become review candidates instead of being
silently overwritten.

Project-specific rules belong in `.embedded-agent/rules/project/`. Durable
project knowledge belongs in `.embedded-agent/knowledge/` or existing project
documentation. Neither location is owned or overwritten by the platform.

A Rule Pack supplies context and constraints. It does not define a mandatory
workflow, expose model reasoning, contain credentials, or authorize tool and
hardware operations.
