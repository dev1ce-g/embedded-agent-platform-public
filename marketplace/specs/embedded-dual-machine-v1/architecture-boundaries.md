# Embedded Architecture Boundary Rules

Read the generated project profile before applying an architecture-specific
rule. A detected boundary is a context and verification requirement, not
permission to operate hardware.

## All Architectures

The following areas require explicit ownership, source-of-truth, and validation
context before code changes:

- power mode, sleep, wake, reboot, heartbeat, and watchdog behavior;
- persistent properties, NVM partitions, queue storage, and generated config;
- OTA, certificate/key storage, secure boot, and cryptographic upgrade paths;
- protocol behavior crossing device, cloud, diagnostics, storage, or another
  ECU;
- SDK, AUTOSAR-generated code, vendor code, and build-system configuration.

## MCU+MPU

For MCU/MPU communication channels, message IDs, payload structs, shared
memory, PMU, OTA, and secure-boot changes, identify:

1. MCU-side owner and path;
2. MPU-side owner and path;
3. shared message, storage, or configuration contract;
4. generated-file source, if any;
5. build and smoke-test path for each affected side.

## MCU+SoC

For MCU/SoC work, also identify the CI manifest and branch revisions, shared
`ctp/src/mpu/*` consumers, modem/GNSS/platform SDK ownership, and rootfs/kernel
or package boundaries. Apply `soc-integration-boundaries.md` when the SoC side
or a shared MCU/SoC contract is in scope.

## MCU-Only

MCU-only does not mean low risk. Confirm the active MCU target, board package,
Keil project, generated configuration source, flash artifact, and target-specific
conditional compilation before changing platform code.
