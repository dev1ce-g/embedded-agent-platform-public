<!-- EMBEDDED-AGENT-PLATFORM:START -->
## Embedded Agent Platform

This project uses model-independent engineering rules under
`.embedded-agent/rules/`. Any capable Agent may own requirements,
architecture, implementation, verification, and delivery when it has the
required repository, tools, and authority.

Before changing embedded source:

1. Read `.embedded-agent/rules/platform/index.md`, applicable project rules,
   the generated project profile, and only the knowledge relevant to the task.
2. Establish the objective, non-goals, owner, active
   repository/workspace/branch/Commit, allowed writes, forbidden actions, and
   acceptance evidence.
3. Prove the active target with build manifests, project files, linked
   libraries, generated configuration, or the real call chain.
4. Select capabilities after discovery. Keep work local when possible; use a
   host Runtime only for toolchain, credential, CI, or device capabilities that
   require it.
5. Use one writer per workspace. Synchronize different workspaces through an
   exact Commit SHA and refuse unknown dirty state.

Use the fixed `embedded-agent` Runtime Interface for Keil, Jenkins, J-Link,
CAN, ADB, SDK, and device operations. A missing capability is a blocker, not
authorization for an ad hoc shell, HTTP, vendor-DLL, or browser path.

Completion requires evidence for every claimed layer. Static checks, host
builds, CI, flash, and observed device behavior are separate claims.
Hardware-changing, repository-changing, release, and production operations
require their explicit Gate.
<!-- EMBEDDED-AGENT-PLATFORM:END -->
