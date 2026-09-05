# Verification Rules

Do not claim completion without reporting the validation actually run.

Use `evidence-first-engineering.md` to separate static, host, selected Target
build, artifact, CI, flash, and observed-device claims. Passing one layer does
not imply another.

For MCU changes, check the active build project, linker/scatter file,
startup/watchdog/HardFault impact, and task stack definitions when touched.

For MPU/application changes, check the active CMake/SDK/package build path and
component membership used by the selected Target.

For cross-CPU behavior, verify both sides of the shared contract and state which
side was changed and which side was only inspected.

For remote Runtime operations:

- consume the fixed Capability Interface and structured result;
- record project/background ID, operation, exit code, and first failure;
- verify build success using the expected marker, log, and fresh artifact
  metadata rather than process launch or exit code alone;
- record exact artifact SHA-256 before flash;
- record device/probe/interface identity and separate erase, program, verify,
  reset, and observed behavior;
- report missing higher-layer evidence explicitly.

Before preparing a commit, inspect tracked and untracked state. Include new files
referenced by build projects deliberately. Commit, push, CI trigger, flash,
reset, CAN transmit, signing, and release require their own authority.
