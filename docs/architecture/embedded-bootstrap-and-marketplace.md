# Embedded Bootstrap And Marketplace

This note defines how a new project joins the embedded Trellis system without
copying a machine Runtime or applying a second full-project preset.

## Ownership Model

| Asset | Owner | Project installation |
|---|---|---|
| Trellis workflow, tasks and hooks | Official Trellis CLI | `trellis init` / `trellis update` |
| Runtime-aware embedded Skills | Platform `skills/` catalog | Machine-level `install.sh` |
| Reusable embedded engineering rules | Internal Spec Marketplace | `--registry` + `--template` |
| Project facts and profiles | Project Discovery | Generated once, refreshed when stale |
| Curated project knowledge | Project repository | Preserved across init/update |
| Host tools, logs, runs and devices | Matching machine Runtime | Installed once per machine |
| Transport client | Calling host Adapter | Installed only when that transport is used |

Platform Skills are installed once per Agent environment. They select fixed
Runtime commands and interpret evidence; they are not copied into product
repositories and do not contain machine configuration or project truth.

The default workflow is Trellis `native`. Embedded behavior extends it through
`.trellis/spec/`; bootstrap does not patch `.trellis/workflow.md`.

## One-Command Entry

The private platform checkout is the default Spec source:

```bash
trellis-embedded-init /path/to/project --discovery local
```

This runs official `trellis init --workflow native`, installs the reusable Spec
from the local private Git checkout, merges the platform-managed project
`AGENTS.md` block, and performs parser-first local discovery. It does not copy
machine runtime or generic knowledge. Repeated runs replace only the platform
block; Trellis-managed and project-owned text is preserved.

For Git worktrees, the bootstrap records `.trellis/`, `.agents/`, `.codex/`,
`.claude/`, and untracked `AGENTS.md` in `.git/info/exclude`. The exclusion is
local to that checkout and does not modify the product repository's committed
`.gitignore`.

Register a Windows workspace only when the project needs Windows Runtime
capabilities:

```bash
trellis-embedded-init /path/to/project \
  --project-id <project-id> \
  --windows-workspace '<windows-workspace>' \
  --build-knowledge
```

Both `--project-id` and `--windows-workspace` are required. Bootstrap only calls
runtime status, project discovery, and optional knowledge build; it cannot
build, flash, reset, or capture RTT.

## Optional Registry Mode

Trellis supports Git-backed private registries through local Git credentials.
For a private mirror, use the SSH source form so the registry probe and template
download use Git instead of an anonymous raw URL:

```bash
export TRELLIS_EMBEDDED_REGISTRY='git@github.com:<owner>/<repository>/marketplace'
trellis-embedded-init /path/to/project
```

Equivalent official Trellis composition:

```bash
trellis init --codex --yes \
  --registry "$TRELLIS_EMBEDDED_REGISTRY" \
  --template embedded-dual-machine-v1 \
  --workflow native \
  --append
```

Registry failure is fatal. Bootstrap does not silently fall back to bundled
files because that could initialize a project from an unintended version.

The short `gh:` form still probes GitHub's raw URL and therefore requires the
repository content to be anonymously readable. Use an SSH registry source for
a private GitHub repository. Bootstrap continues to detect `Error:`/`Fatal:`
output and verifies the expected Spec index, so a false-success response fails
closed.

## Existing Project Refresh

To refresh only generated local profiles without reconfiguring Trellis:

```bash
trellis-embedded-init . --skip-trellis-init --discovery local --json
```

To inspect a Spec fallback update without overwriting project rules:

```bash
python3 <platform-source>/bootstrap/apply_embedded_preset.py \
  --target . --dry-run --json
```

For an offline checkout of this platform repository, add `--local-template`.

Conflicts become `*.embedded-dual-machine.new`. `--overwrite-spec` and the
compatibility adapter's `--overwrite` are explicit review decisions.

## Upgrade Sequence

```bash
trellis upgrade
trellis update --dry-run
trellis update --create-new
```

`trellis update` does not subscribe project-owned Spec or custom Workflow files
to a remote marketplace. Version template IDs for breaking changes and review
project migrations separately.
