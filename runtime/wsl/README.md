# WSL Runtime Adapter

`bin/embedded-agent` calls an installed Windows Native Runtime through WSL
interop. It forwards a Base64-encoded argument array and exposes no arbitrary
shell command interface.

Install the Windows Runtime first, then configure its WSL path:

```bash
export WSL_EMBEDDED_AGENT_PREFIX='/mnt/c/Users/you/AppData/Local/EmbeddedAgentPlatform'
embedded-agent status --json
```

The prefix derives the stable Windows entry path. Advanced deployments may
override that entry with `WSL_EMBEDDED_AGENT_SCRIPT`. State and backend paths
remain owned by the installed Windows launcher and cannot be overridden by the
transport. Set `WSL_WINDOWS_PY` only when `where py` cannot locate the Windows
Python launcher.
