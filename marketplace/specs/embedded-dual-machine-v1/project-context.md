# Project Context

This Trellis workspace is an embedded project. Fill in concrete platform facts
before changing target-specific code.

Suggested facts to record:

* MCU repository or package path.
* MPU/application repository or package path.
* active MCU target, board package, compiler and build project.
* active MPU module, SDK image/version and build entry.
* remote build host alias and remote workspace root, if any.
* known open questions that must be verified before low-level changes.

Keep product-specific business knowledge out of this generic spec. Put subsystem
topology and operational details under `.trellis/knowledge/`.
