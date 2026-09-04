# Git Conventions

Commit style follows the repository. Embedded task branch naming is canonical
across projects so Mac, Windows, Jenkins and model-worker evidence refer to one
stable identity.

## Commit Messages

Use the current repository's dominant style. When no stable style exists, use a
concise conventional form:

```text
<type>(<scope>): <summary>
```

Common types are `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `chore`, and
`revert`. Explain non-obvious behavior, risk, and verification in the body.

## Branches And Baselines

- New task branches must use:

  ```text
  <developer>-<task-slug>-<YYYYMMDD>
  ```

  Examples:

  ```text
  sample.dev-uds-timeout-recovery-20260718
  sample.dev-production-test-soc-20260718
  sample.dev-production-test-mcu-20260718
  ```

- `developer` identifies the human owner. Change types and model names such as
  `feat`, `fix`, `ai`, `codex`, `grok` or `claude` are forbidden prefixes.
- `task-slug` is lowercase ASCII kebab-case. Put a cross-repository component
  such as `mcu`, `soc`, `autosar` or `ci` at the end of the slug, before date.
- Do not use slash-style task branches such as `feat/project-task`. Change type
  belongs in the Commit Message, not the branch name.
- `main`, `master`, `dev`, `baseline_dev` and human-managed `release/*` are
  lifecycle branches, not task-branch examples.
- Determine the baseline from the current repository, CI manifest, or explicit
  task contract.
- Do not assume `main`, `master`, `dev`, or `baseline_dev` without evidence.
- Historical remote branches may remain as immutable evidence. Never create new
  work on them merely because their old names are non-compliant.

Before creating a branch, use the machine-level policy command:

```bash
trellis-branch create \
  --repo <repository> \
  --developer sample.dev \
  --task production-test \
  --component soc \
  --date 20260718 \
  --base <verified-base-ref> \
  --json
```

The command refuses dirty worktrees, invalid names, missing bases and duplicate
local branches. It creates no upstream and performs no push. On entry to an
existing task workspace, validate before editing:

```bash
trellis-branch check --repo <repository> --developer sample.dev --json
```

If the check fails, stop before coding. Rename an unpublished local branch or
create a compliant branch from the reviewed Commit. Shared remote branch
renames remain an explicit Git operation requiring authorization.
For read-only inspection of a lifecycle branch, `check --allow-protected` may
be used; it never authorizes source writes on that branch.

## Agent Rules

- Inspect `git log --oneline -5` before drafting commits.
- Record the generated branch name and exact base Commit in the Trellis task,
  Delegation Packet and Windows Job Packet. Do not hand-type an alternative.
- A separate clone or model-worker Worktree does not relax this rule; run the
  machine-level check even when `.trellis/` is absent from that checkout.
- Present a commit plan for user confirmation before committing.
- Do not push, merge, rebase, reset, or rewrite history without explicit
  authorization.
- Keep Trellis bookkeeping commits after the implementation commits they
  describe.
