# Verification Rules

Do not claim completion without reporting actual validation that was run.

Use `evidence-first-engineering.md` to separate static, host, Windows build,
artifact, Jenkins and device claims. Passing one layer does not imply another.

For MCU-side changes, check the relevant build project, linker/scatter file,
startup/watchdog/HardFault impact and task stack definitions when touched.

For MPU/application changes, check the active CMake/SDK/package build path and
the component membership used by the target build.

For cross-CPU behavior, verify both sides of the shared contract and state
whether both sides needed edits.

For remote Windows builds:

* use the wrapper documented in `.trellis/knowledge/build/remote-agent-command-layer.md`.
* treat wrapper JSON, remote log paths and artifact timestamps as evidence.
* treat `hq claude --execute` output and `handoff.md` as task evidence, not as
  build proof by themselves.
* verify Keil success from the wrapper exit code, build log success marker, and
  fresh artifact metadata when an artifact is expected.
* inspect `handoff.md`, `remote-sessions.jsonl`, and referenced Windows logs
  before claiming a remote agent task is complete.
* do not claim success from a launched GUI process, a missing log, a stale
  artifact or local-only static checks.

Before preparing a task commit, inspect tracked and untracked state. New files
referenced by build projects must be included deliberately.
