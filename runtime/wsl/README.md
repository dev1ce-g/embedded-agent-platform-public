# WSL Runtime Adapter

`bin/embedded-agent` calls an installed Windows Native Runtime through WSL
interop. It forwards a Base64-encoded argument array and exposes no arbitrary
shell command interface.

Install the Windows Runtime first, then configure its WSL path:

```bash
export WSL_EMBEDDED_AGENT_PREFIX='/mnt/c/Users/you/AppData/Local/EmbeddedAgentPlatform'
embedded-agent status --json
```

The prefix derives the Windows entry, state root, and backend paths. Advanced
deployments may override them individually with `WSL_EMBEDDED_AGENT_SCRIPT`,
`WSL_EMBEDDED_AGENT_ROOT`, and `WSL_EMBEDDED_AGENTCTL`. Set `WSL_WINDOWS_PY`
only when `where py` cannot locate the Windows Python launcher.
