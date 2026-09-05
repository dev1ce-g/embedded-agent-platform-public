# Embedded Agent Platform

[English](README.md) | [简体中文](README.zh-CN.md)

A model-agnostic context and capability plane for brownfield embedded
engineering. AI agents provide reasoning; this platform provides project facts,
engineering rules, bounded tools, safety gates, durable jobs, and auditable
evidence across heterogeneous hosts and devices.

The platform is not a workflow engine and does not require or launch a specific
model. Existing agents consume the same project context and fixed Runtime
interfaces through CLI, Skills, or future protocol adapters.

Current status: **`0.2.0` release candidate**. It is not yet a tagged release.
Review the [changelog](CHANGELOG.md), the
[`0.1` to `0.2` upgrade guide](docs/migration/0.1-to-0.2.md), and the
[software acceptance boundary](docs/releases/0.2.0.md) before adopting it.

## Repository Layout

```text
rules/           Reusable embedded engineering rule packs
contracts/       Capability request/result contracts
skills/          Runtime-aware, model-portable skills
bootstrap/       Project projection, discovery, migration, and tests
runtime/mac/     macOS/Linux SSH transport adapter for a Windows Runtime
runtime/wsl/     WSL-to-Windows interoperability adapter
runtime/windows/ Windows Runtime and tool/hardware adapters
docs/            Architecture, migration, and operations documentation
```

See the [platform capability model](docs/architecture/platform-capability-model.md)
and [project projection model](docs/architecture/project-projection-and-context.md).
The executed refactoring plan and remaining roadmap are recorded in
[Trellis Removal And Platform Refactoring](docs/refactoring/trellis-removal.md).

## Project Context

Initialization creates a local projection without imposing tasks or a workflow:

```text
.embedded-agent/
  manifest.json     platform-managed projection metadata
  rules/platform/  platform-managed engineering rules
  rules/project/   project-owned rule overrides
  context/         generated project and target facts
  knowledge/       project-owned durable knowledge
  evidence/        optional local Runtime/adapter evidence cache
```

Generated context and managed rules are local by default. Project-owned rules
and knowledge are not excluded as a group, so a project can version them or
point agents at existing documentation.

## Quick Start (macOS, Linux, or WSL)

Install the local project and branch-policy tools, host adapter, and bundled
Skills (`embedded-project`, `embedded-agent-branch`, and `embedded-agent`):

```bash
./install.sh
```

The installer creates links back to this checkout, so keep the checkout in
place. The default command directory is `~/.local/bin`; ensure it is on `PATH`:

```bash
export PATH="${HOME}/.local/bin:${PATH}"
```

Override it with `EMBEDDED_PLATFORM_BIN_DIR`, and override the Skill directory
with `EMBEDDED_PLATFORM_SKILL_DIR`.

Initialize and inspect a project without Trellis or any model-specific CLI:

```bash
embedded-project init /path/to/project --discovery local --json
embedded-project doctor /path/to/project --json
embedded-project refresh /path/to/project --discovery local --json
```

To register a Windows-backed project, provide its stable identity and actual
workspace explicitly. First configure the installed transport and prove that
the Runtime is reachable. For macOS or Linux over SSH:

```bash
export EMBEDDED_AGENT_HOST='<ssh-host-alias>'
export EMBEDDED_AGENT_REMOTE_PREFIX='C:\Users\<user>\AppData\Local\EmbeddedAgentPlatform'
embedded-agent status --json
```

For WSL, set `WSL_EMBEDDED_AGENT_PREFIX` to the mounted Windows install root
and run the same status check. Then initialize the project:

```bash
embedded-project init /path/to/project \
  --project-id <project-id> \
  --windows-workspace '<windows-workspace>' \
  --build-knowledge \
  --json
```

The Windows path must resolve below the Runtime machine's
`EMBEDDED_AGENT_WORKSPACE_ROOT`.

Bootstrap only performs projection, read-only discovery, Runtime status, and an
optional knowledge build. It never builds, flashes, resets, triggers CI, or
operates a device.

## Windows Runtime

Python 3.9 or newer is required:

```powershell
git clone https://github.com/dev1ce-g/embedded-agent-platform-public.git
cd embedded-agent-platform-public
py -3 runtime\windows\install.py
& "$env:LOCALAPPDATA\EmbeddedAgentPlatform\embedded-agent.cmd" status --json
```

Toolchains and vendor utilities are not bundled. The Mac and WSL clients forward
argument arrays to this fixed Runtime surface; they do not duplicate its gates
or business logic.

## Migrating Existing Projects

Migration is explicit, one-way, and non-destructive:

```bash
embedded-project migrate-trellis /path/to/project --dry-run --json
embedded-project migrate-trellis /path/to/project --json
embedded-project init /path/to/project --discovery local --json
embedded-project doctor /path/to/project --json
```

The migration imports project context, knowledge, and project-owned rules. It
does not call Trellis, delete `.trellis/`, or reactivate old workflows, hooks,
agents, or tasks. Migration skips Discovery, so follow it with `init` (or
`refresh`) and `doctor`; use Windows discovery when that host owns the canonical
toolchain facts. See [the migration guide](docs/migration/from-trellis.md).

## Safety and Tests

Runtime operations that mutate repositories, CI, or devices use fixed commands
and explicit confirmation gates. Do not commit credentials, private keys,
project source copies, device logs, generated context, or proprietary binaries.

```bash
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s bootstrap/tests -v

cd runtime/windows/embedded-agent
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s tests -v
```

Hardware, Jenkins, signing, flashing, and device tests require explicit
configuration and authorization and are not run by default.

For a reproducible deployment, install from a reviewed commit. After the
release is tagged, use `v0.2.0` instead of following a moving `main` branch.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and
[SECURITY.md](SECURITY.md) for private vulnerability reporting.

Licensed under the [Apache License 2.0](LICENSE).
