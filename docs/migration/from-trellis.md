# Migrating From Trellis

This migration removes Trellis from the active project architecture while
preserving project-owned knowledge and reviewable history.

For host installation, Runtime CLI, and machine-registry changes, start with
the complete [`0.1` to `0.2` upgrade guide](0.1-to-0.2.md).

## Guarantees

`embedded-project migrate-trellis`:

- reads an existing `.trellis/` only when explicitly requested;
- never invokes the Trellis CLI;
- never modifies or deletes the source projection;
- never turns old workflow, hooks, agents, runtime sessions, or tasks into
  active platform state;
- skips identical files and never silently overwrites different content;
- makes `.embedded-agent/` the only active projection.

## Mapping

| Old source | New destination | Handling |
| --- | --- | --- |
| `.trellis/spec/project/*` | `.embedded-agent/context/*` | Imported as legacy context; refresh Discovery afterward |
| `.trellis/knowledge/project/**` | `.embedded-agent/knowledge/project/**` | Imported as project-owned knowledge |
| Project-owned files in `.trellis/spec/` | `.embedded-agent/rules/project/` | Imported for review |
| Bundled platform Spec files | `.embedded-agent/knowledge/legacy-trellis-spec/` | Archived for review; the latest Rule Pack is installed separately into `rules/platform/` |
| `.trellis/tasks/` | Original location only | Reported as legacy history |
| `.trellis/workflow.md`, hooks, agents, `.runtime/` | Original location only | Reported as unsupported legacy state |

Old task documents may contain useful decisions. Extract confirmed conclusions
into project Knowledge; do not restore their execution state or stage sequence.

## Procedure

Preview first:

```bash
embedded-project migrate-trellis /path/to/project --dry-run --json
```

Review destinations, conflicts, and ignored legacy state. Then run:

```bash
embedded-project migrate-trellis /path/to/project --json
embedded-project init /path/to/project --discovery local --json
embedded-project doctor /path/to/project --json
```

Use Windows discovery instead of local discovery when the canonical toolchain
facts exist only in the registered Windows workspace.

## Conflict Handling

If a destination already contains different content, migration creates or
reports a deterministic candidate rather than overwriting the project file.
Compare the candidate with the active project rule or knowledge document and
promote only the confirmed result.

The old `.trellis/` remains recoverable after migration. Removing it is a
separate project-owner decision after the new projection, Agent entry, and
relevant knowledge have been reviewed.
