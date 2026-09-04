# SoC Integration Boundary Rules

MCU+SoC projects use the MCU project repo plus shared SoC components from the CI
manifest. Do not infer the SoC side from the local project directory alone.
Always read the ancestor CI manifests, for example:

```text
CTP/ci/{ci-repo}/manifests/mcu_*.xml
CTP/ci/{ci-repo}/manifests/mpu_*.xml
```

## Source Ownership

* MCU code normally lives under `ctp/src/project/{project}/r01v01/mcu` or a
  chip-specific MCU repo referenced by `mcu_*.xml`.
* SoC application and library code normally lives under shared repos such as
  `ctp/src/mpu/app/*`, `ctp/src/mpu/lib/*`, `home/platform/*` or project CI
  paths ending in `*_mpu/*`.
* Board/project variants such as `cbb_srt_{project}` and
  `project_config_{project}` are SoC-side integration points and must be treated
  as shared contracts, not isolated local files.
* SDK, platform rootfs/kernel, toolchains and generated package outputs are
  source-of-truth boundaries. Do not edit them unless the task explicitly owns
  that layer.

## Before Changing Code

For any task touching the SoC side or MCU/SoC interaction, record:

1. the exact CI repo and manifest names used for context;
2. MCU-side repo/path and branch;
3. SoC-side repo/path and branch;
4. the communication contract, property, file, protocol or generated config
   being changed;
5. the required build, package or smoke-test command on Windows.

If the affected SoC component is shared by multiple products, treat the change
as cross-project until proven otherwise.

## Verification

* MCU-only edits require the MCU build path from the Windows workspace.
* SoC or cross-chip edits require the relevant SoC/CMake/package verification
  in addition to MCU validation when the contract crosses both sides.
* Completion evidence must include the manifest path, command used, exit status
  and key log/artifact locations.
