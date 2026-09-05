# Git Conventions

Repository-local policy takes precedence. The platform requires traceable source
identity and safe synchronization; it does not require every project to adopt
one branch naming scheme.

## Source Identity

Before writing or invoking a capability, record:

- repository root and remote when relevant;
- current branch or detached state;
- exact Commit SHA;
- tracked, untracked, staged, and unmerged state;
- selected build Target's membership in that source.

Do not infer a baseline from a conventional branch name. Use the project,
manifest, CI, or explicit owner decision.

## Commits And Synchronization

- Follow the repository's existing commit style.
- Stage only reviewed paths and inspect staged changes before commit.
- Do not commit, push, merge, rebase, reset, clean, or rewrite history without
  corresponding authority.
- Formal cross-workspace synchronization uses commit, push/fetch, exact checkout,
  and clean-state verification.
- Never overwrite a dirty or divergent workspace to make it match another host.

## Optional Reference Branch Policy

Projects that choose the bundled reference convention may use:

```text
<developer>-<task-slug>-<YYYYMMDD>
```

The machine-level helper validates and creates this format without a push:

```bash
embedded-agent-branch create \
  --repo <repository> \
  --developer sample.dev \
  --task production-test \
  --component soc \
  --date 20260718 \
  --base <verified-base-ref> \
  --json

embedded-agent-branch check \
  --repo <repository> \
  --developer sample.dev \
  --json
```

The helper refuses dirty worktrees, invalid dates/names, missing bases, duplicate
branches, and writes on protected lifecycle branches. It is a policy utility,
not part of the Capability Runtime and does not authorize Git mutations beyond
the requested local branch creation.

If a project uses another valid convention, document it in `AGENTS.md` or
`.embedded-agent/rules/project/` and use the project's own checked tooling.
