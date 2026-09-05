# Agent Delegation Guide

Delegation is optional. Use it for bounded parallel discovery, independent
review, or a result that requires another host or capability.

## Delegation Contract

Every delegated result should state:

- objective and excluded work;
- repository, workspace, branch, and exact Commit;
- read/write scope and one-writer ownership;
- relevant rules, context, and knowledge;
- forbidden operations and required Gates;
- expected evidence and output format;
- whether the delegate may make design decisions or only return facts.

A remote Agent may own an entire project only when that ownership is explicit.
A Runtime Job is not an Agent and cannot own design or acceptance.

## Safe Parallelism

- Use read-only delegates for broad search and independent verification.
- Use separate worktrees or workspaces for parallel writers.
- Do not let a delegate call a device, CI, credentials, or repository mutation
  capability unless the contract grants it.
- Do not ask multiple delegates to edit the same workspace.
- Return concise conclusions, exact references, conflicts, and open questions;
  omit raw search noise.

## Handoff

Carry forward the same objective, source SHA, permissions, decisions, and
evidence references when work changes host or model. Important delegate claims
remain evidence leads until the outcome owner verifies them.

Delegation does not create a mandatory task store, workflow, or model hierarchy.
