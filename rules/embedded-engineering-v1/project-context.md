# Project Context

Record concrete project facts before changing target-specific code:

- MCU repository or package path.
- MPU/application repository or package path.
- Active MCU target, board package, compiler, linker file, and build project.
- Active MPU module, SDK image/version, and build entry.
- Generated configuration and prebuilt-library ownership.
- Runtime project ID and remote workspace, if a host Adapter is required.
- Known ambiguities that block implementation or verification.

Generated facts belong in `.embedded-agent/context/` and must include source
and confidence. Product architecture, confirmed decisions, failure patterns,
and runbooks belong in `.embedded-agent/knowledge/` or existing project docs.

Do not put product-specific facts into the reusable Rule Pack. Do not promote a
generated inference into a rule without review.
