# Platform Operating Model

Use this rule when deciding which Agent or host owns an embedded task.

## Ownership

Any capable Codex task may own the complete project lifecycle: requirement
intake, architecture, planning, implementation, verification and delivery.
Mac, WSL and Windows are host choices, not permanent Agent roles.

For each task, record:

- one outcome owner.
- the active repository, workspace, branch and Commit.
- allowed writes and forbidden actions.
- required capabilities and the Adapter selected for each capability.
- acceptance evidence and remaining risk.

Use one writer per workspace. Use an independent worktree or workspace for
parallel writers.

## Capability Routing

Keep work local when the current host has the repository, tools and authority.
Delegate only the result that requires another context or capability. A remote
Codex task receives a self-contained task contract and may perform architecture
or implementation work when that contract gives it ownership.

Use Windows Native Runtime only for capabilities that require it, including
Windows toolchains, Jenkins credentials, J-Link, CAN, ADB and connected devices.
The Runtime is an Adapter behind a fixed command, Gate and evidence Interface;
it is not the owner of project decisions.

When source crosses workspaces, use Git and an exact Commit SHA. Treat a dirty,
missing or divergent workspace as a blocking state rather than overwriting it.

## Trellis Flow

Keep the workflow host-neutral:

1. Freeze objective, constraints, authority and acceptance criteria.
2. Prove the active target and load only relevant Spec and Knowledge.
3. Record architecture decisions and verification strategy.
4. Implement in the owner workspace.
5. Route only missing capabilities through an Adapter.
6. Verify each claimed layer and deliver auditable evidence.

Changing host does not restart the task or discard its decisions. Preserve the
same task contract and update the Context Packet when evidence changes a
decision.
