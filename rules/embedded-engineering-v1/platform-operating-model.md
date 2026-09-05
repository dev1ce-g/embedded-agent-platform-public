# Platform Operating Model

Use these rules when deciding which Agent, host, or Adapter owns an embedded
engineering result.

## Ownership

Any capable Agent may own the complete lifecycle: requirement clarification,
architecture, implementation, verification, and delivery. Mac, WSL, Windows,
Linux, and CI are capability locations, not permanent roles.

For each material change, establish:

- one outcome owner;
- active repository, workspace, branch, and exact Commit;
- allowed writes and forbidden actions;
- required context with source and freshness;
- required capabilities and selected Adapters;
- acceptance evidence and remaining risk.

Use one writer per workspace. Parallel writers require independent worktrees or
workspaces.

## Capability Routing

Keep work local when the current host has the repository, tools, and authority.
Route only the missing capability. Windows Native Runtime is used for
Windows-local toolchains, credentials, drivers, and devices; it does not own
project decisions.

When source crosses workspaces, use Git and an exact Commit SHA. Dirty, missing,
or divergent state is blocking rather than permission to overwrite it.

## Engineering Completion Conditions

The platform does not prescribe a fixed workflow. The Agent may organize work
as appropriate, but it must:

1. establish objective, boundaries, authority, and acceptance;
2. prove the active Target before target-specific writes;
3. use only fixed Capability Interfaces for controlled operations;
4. preserve corrections and invalidate superseded assumptions;
5. obtain evidence proportional to the claimed result;
6. report unverified layers and recovery paths.

Changing host, model, or Agent does not discard the task goal, decisions,
permissions, source identity, or accumulated evidence.
