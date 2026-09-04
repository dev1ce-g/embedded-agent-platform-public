<!-- EMBEDDED-AGENT-PLATFORM:START -->
## Embedded Agent Platform

This project uses the Embedded Agent Platform rules under `.trellis/spec/`.
Read `platform-operating-model.md` before assigning work by host. A Mac, WSL or
Windows Codex task may own requirements, architecture, implementation,
verification and delivery when it has the required repository, tools and
authority.

Before changing embedded source:

1. Read `.trellis/spec/project-onboarding.md`, the generated project profile,
   and only the Spec/Knowledge files relevant to the task.
2. Freeze one outcome owner, the active repository/workspace/branch/Commit,
   allowed writes, forbidden actions and acceptance criteria.
3. Prove the active target with build manifests, project files, linked
   libraries, generated configuration or the real call chain.
4. Select capabilities after discovery. Keep work local when possible; use a
   host Runtime only when its toolchain, credential or device capability is
   required.
5. Use one writer per workspace. Synchronize different workspaces through the
   task branch and exact Commit SHA.

During implementation:

- Maintain the same Trellis task and Context Packet when work changes host.
- Freeze user corrections and remove invalidated assumptions before continuing.
- Prefer the simplest design that satisfies the active project contract.
- Use the Windows Runtime fixed Interface for Keil, Jenkins, J-Link, CAN, ADB,
  SDK and device operations. A Runtime failure is a blocker for that capability,
  not permission to create a direct shell, HTTP or browser path.
- Treat Runtime Jobs, remote Codex tasks and native subagents as different
  objects with different owners and lifetimes.
- For logs, identify clock domain, wrap/restart boundaries, event anchors and
  missing intervals before calculating latency.

Completion requires evidence for every claimed layer. Exit code alone is not
build proof; check the expected marker, log path and fresh artifact metadata.
Static checks, host builds, CI, flash and runtime behavior are separate claims.
Hardware-changing and release operations require their explicit Gate.
<!-- EMBEDDED-AGENT-PLATFORM:END -->
