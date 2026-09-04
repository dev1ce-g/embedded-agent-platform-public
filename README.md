# Embedded Agent Platform

[English](README.md) | [简体中文](README.zh-CN.md)

Reusable Trellis specifications, bootstrap tools, and controlled runtime
adapters for embedded development. The platform keeps host-specific toolchains,
CI services, and hardware behind bounded JSON command interfaces.

## What Is Included

```text
marketplace/     Reusable embedded-platform specifications
skills/          Runtime-aware Agent Skills
bootstrap/       Project initialization, discovery, and tests
runtime/mac/     SSH client for a Windows Runtime
runtime/wsl/     WSL interoperability client
runtime/windows/ Windows Runtime and hardware/tool adapters
docs/            Architecture and operations documentation
```

See the [platform capability model](docs/architecture/platform-capability-model.md)
and [host topology](docs/architecture/dual-machine-agent-system.md) for the
architecture and trust boundaries.

## Quick Start

Clone or download the repository. No repository-specific absolute path is
required.

### Windows local runtime

Python 3.9 or newer is required.

```powershell
git clone https://github.com/your-organization/embedded-agent-platform.git
cd embedded-agent-platform
py -3 runtime\windows\install.py
& "$env:LOCALAPPDATA\EmbeddedAgentPlatform\embedded-agent.cmd" status --json
```

Use `--prefix C:\Your\Install\Directory` to choose another installation
directory. Re-running the installer updates managed source files and preserves
the separate `state` directory. Copy the generated `config.example.ps1` and set
only the integrations you use. Toolchains and vendor utilities are not bundled.

### Mac or WSL client

```bash
./install.sh
```

The Mac client needs an SSH host and the Windows install path:

```bash
export EMBEDDED_AGENT_HOST='windows-host'
export EMBEDDED_AGENT_REMOTE_PREFIX='C:\Users\you\AppData\Local\EmbeddedAgentPlatform'
embedded-agent status --json
```

The WSL client needs the same install location expressed as a WSL path:

```bash
export WSL_EMBEDDED_AGENT_PREFIX='/mnt/c/Users/you/AppData/Local/EmbeddedAgentPlatform'
embedded-agent status --json
```

## Initialize a Project

```bash
trellis-embedded-init /path/to/project --discovery local
```

The bootstrap installs the checked-out specifications into the target project
and preserves project-owned content. For a Windows-backed project, register the
actual workspace explicitly:

```bash
trellis-embedded-init /path/to/project \
  --project-id <project-id> \
  --windows-workspace '<windows-workspace>' \
  --build-knowledge
```

Project workspaces, build tools, Jenkins endpoints, credentials, Aboot tools,
firmware packages, and CAN vendor libraries are local configuration. See
[`runtime/windows/config.example.ps1`](runtime/windows/config.example.ps1) for
the supported environment variables.

## Safety

Bootstrap does not build, flash, reset, capture RTT, operate devices, or modify
credentials. Runtime commands that mutate repositories or devices use explicit
confirmation gates. Do not commit credentials, private keys, project source,
device logs, generated profiles, or proprietary vendor binaries.

## Tests

```bash
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s bootstrap/tests -v

cd runtime/windows/embedded-agent
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s tests -v
```

GitHub Actions runs the runtime suite on both Ubuntu and Windows. Hardware,
Jenkins, signing, flashing, and device tests require an explicitly configured
environment and are not run by default.

## Contributing and Security

See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and
[SECURITY.md](SECURITY.md) for private vulnerability reporting guidance.

Licensed under the [Apache License 2.0](LICENSE).
