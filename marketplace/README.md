# Embedded Spec Marketplace

Marketplace source path after publishing to a Trellis-accessible Git source:

```text
<registry-source>/marketplace
```

Direct Trellis usage:

```bash
trellis init --codex --yes \
  --registry <registry-source>/marketplace \
  --template embedded-dual-machine-v1 \
  --workflow native \
  --append
```

The marketplace installs only `.trellis/spec/`. Runtime code, project
knowledge, logs, tasks, and device state are deliberately outside this
contract.

For a private mirror, use an SSH registry source so the marketplace is read
through local Git credentials:

```text
git@github.com:<owner>/<repository>/marketplace
```

The short `gh:` form uses GitHub's anonymous raw URL and is suitable for public
registry content. Local template mode remains the deterministic offline fallback.
