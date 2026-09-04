# Contributing

Keep changes scoped to one platform layer and preserve the fixed Runtime
command surface, confirmation gates, and path boundaries. Do not add machine
credentials, product source, device logs, proprietary binaries, or personal
absolute paths.

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
