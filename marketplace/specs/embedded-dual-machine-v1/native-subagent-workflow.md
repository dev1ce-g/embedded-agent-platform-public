# Native Read-Only Scout Workflow

Native Codex subagents are disposable evidence scouts. They reduce main-thread
context pollution from broad searches and independent verification. They do not
replace Trellis planning, Grok coding workers or the Windows Runtime.

## Role Boundary

```text
Codex main agent       planning, decisions, review and acceptance
Native scout           read-only exploration, search and verification
Grok worker            bounded coding and local tests in a task worktree
Windows embedded-agent build, Jenkins, flash, RTT and runtime evidence
```

A scout must not modify files, choose the final design, create branches, commit,
push, start Grok, call `embedded-agent`, operate devices or spawn another agent.

## Routing

Handle work directly when it is a known small file, a single fact, the exact
code about to be modified, or a foundation document whose details establish the
main agent's architecture view.

Use scouts for:

- large files that are not foundation documents;
- cross-file or cross-directory searches;
- independent and parallel evidence gathering;
- rechecking module state during a long task;
- noisy logs, broad search output and peripheral material.

Delegation is justified only when it reduces main-thread context, improves
parallelism or provides meaningful independent verification.

## Delegation Packet

Every scout request must be self-contained and include:

- repository and read-only scope;
- the exact question to answer;
- known constraints and excluded actions;
- expected output fields;
- required `file:line`, symbol names and minimal verbatim evidence;
- a statement that facts and inference must be separated.

Use a fresh context (`fork_turns = "none"`) when the available native protocol
supports it. Do not copy an already long parent conversation into evidence
scouts.

## Scheduling And Verification

- Dispatch independent scouts together, within the runtime concurrency limit.
- After dispatch, wait for them instead of repeating their searches in the main
  thread.
- Treat scout output as evidence leads, not accepted truth.
- Verify important or suspicious claims through the returned locations and
  excerpts. Do not reread the entire searched corpus merely to duplicate work.
- Close one-shot scouts after their result is collected.
- A scout running for ten minutes without useful output is unhealthy. Inspect
  available partial evidence, stop it and narrow or split the request.

## Context Packet Integration

Only durable conclusions, exact references, unresolved conflicts and remaining
questions flow back into the Trellis Context Packet. Raw grep output, discarded
hypotheses and repeated logs remain outside the main context.
