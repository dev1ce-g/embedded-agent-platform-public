# Contributing

Keep changes scoped to one platform layer and preserve the fixed Runtime
command surface, confirmation gates, and path boundaries. Do not add machine
credentials, product source, device logs, proprietary binaries, or personal
absolute paths.

Changes to public JSON fields, risk gates, or evidence semantics must update
`contracts/`, the affected Rule Pack, and tests together. Project bootstrap
must remain model-independent, idempotent, and usable without Trellis.

Before opening a pull request, run:

```bash
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s bootstrap/tests -v

cd runtime/windows/embedded-agent
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s tests -v
```

Also run `git diff --check` and review the diff for generated artifacts and
local configuration. Hardware, Jenkins, flashing, signing, and device tests
must only run in an explicitly authorized environment.

On a POSIX host, also validate the installer and transport adapters:

```bash
bash -n install.sh runtime/mac/bin/embedded-agent runtime/wsl/bin/embedded-agent
```
