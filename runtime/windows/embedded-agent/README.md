# Windows Local Embedded Agent

This Runtime exposes Windows-local embedded toolchains and devices through a
fixed JSON interface. It does not provide an arbitrary shell command endpoint.

## Install

From the repository root:

```powershell
py -3 runtime\windows\install.py
& "$env:LOCALAPPDATA\EmbeddedAgentPlatform\embedded-agent.cmd" status --json
```

The default layout is:

```text
%LOCALAPPDATA%\EmbeddedAgentPlatform\
  VERSION
  embedded-agent.cmd
  config.example.ps1
  aboot-connections.example.json
  jenkins-connections.example.json
  bin\
  embedded-agent\
  can-runtime\
  state\
```

Pass `--prefix` to select another directory. The installer is idempotent: it
updates managed program files without deleting the separate state directory.
It does not install Keil, J-Link, Aboot, ADB, CAN vendor DLLs, Jenkins
credentials, or proprietary SDK tools.

## Configure

Copy `config.example.ps1`, edit the copy outside the repository, and load it
before starting the Runtime. Required values depend on the command being used.

Common settings:

| Variable | Purpose |
|---|---|
| `AGENTCTL_UV4_PATH` | Keil UV4 executable |
| `AGENTCTL_JLINK_PATH` | SEGGER J-Link Commander executable |
| `EMBEDDED_AGENT_WORKSPACE_ROOT` | Root for managed project workspaces |

Every `project discover` and `git clone` workspace must resolve inside this
machine-owned root without a symlink or reparse-point hop. Set it to the common
parent of existing workspaces before registering projects; a request cannot
expand the boundary. The Runtime revalidates the persisted workspace against
that boundary on every background load, so replacing it or an ancestor with a
junction fails closed.

The Runtime otherwise stores mutable state under
`%LOCALAPPDATA%\EmbeddedAgentPlatform\state` and uses install-relative backend
paths. A machine deployment may set `EMBEDDED_AGENT_INSTALL_ROOT` before the
launcher starts; transport payloads and `EMBEDDED_AGENT_ROOT` cannot override
the stable launcher's state root. Python backend locations are not configurable:
the Runtime accepts only regular, non-symlink resources from its own installation.
The SDK Manager capability reports unavailable until a manager is shipped as a
Runtime-owned resource; an environment variable or CLI argument cannot supply
an executable manager.

The current Runtime treats machine tool configuration and executable project
build inputs as administrator/project-owner trust boundaries. In particular,
Keil project hooks and an existing MPU builder container are not a general host
sandbox. Until lifecycle Preflight validates those inputs, register only trusted
workspaces, use a dedicated least-privilege Runtime account, and provision MPU
containers without extra writable host mounts, Docker socket access, privileged
mode, host namespaces, devices, or added capabilities.

### Aboot connections

Copy `aboot-connections.example.json` to `aboot-connections.json` next to
`embedded-agent.cmd`. Each opaque connection id binds one canonical
`adownload.exe` and one approved firmware root. The executable must be a regular
non-reparse file and its SHA-256 is mandatory. Restrict the registry, tool and
firmware directory with Windows ACLs. MPU flash callers pass only
`--connection-id`; `--aboot-root`, `--firmware-root` and their former
environment equivalents are not accepted.

### CAN drivers

Copy `can-runtime\can-drivers.example.json` to `can-drivers.json` next to
`embedded-agent.cmd`. This fixed, machine-owned registry binds `controlcan` and
`zcanpro` to canonical absolute DLL paths and optionally to SHA-256 digests and
vendor-compatible Python executables. Physical CAN capabilities fail closed
when the registry is absent or invalid. Task environment variables cannot
select a DLL, and the retained `--dll` compatibility option accepts only the
exact path already selected by the registry. Restrict the registry and vendor
files with Windows ACLs; see `can-runtime\README.md` for the schema.

### Jenkins connections

Copy `jenkins-connections.example.json` to `jenkins-connections.json` under the
install root. This location is fixed relative to the installed Runtime and
cannot be redirected by task environment or CLI input. Each entry binds one
opaque `connection_id` to exactly one server and one absolute credential-file
path. The registry contains no credential values; commands accept only
`--connection-id`, never a server or credential path.

Restrict both files with Windows ACLs. The Runtime account needs read access;
the remote caller and project accounts must not have write access to either the
registry or credential file. Configure the environment and ACLs as machine
administration, not as task-provided CLI input. If the caller can rewrite the
registry, the origin binding is not a security boundary.

Runtime 0.2 intentionally removes the Jenkins `--server` and `--config` CLI
options. Authenticated requests, queue polling and artifact downloads reject a
URL or redirect whose origin differs from the selected connection.

## Use

```powershell
$env:EMBEDDED_AGENT_WORKSPACE_ROOT = 'C:\work'
embedded-agent.cmd status --json
embedded-agent.cmd project discover --project demo --workspace C:\work\demo --json
embedded-agent.cmd build --project demo --target keil --json
embedded-agent.cmd jenkins --connection-id firmware-ci auth-check --json
embedded-agent.cmd flash --project demo --target mpu --connection-id lab-mpu --package release.zip --usb-only --require-confirm --confirm --json
embedded-agent.cmd can driver-list --json
```

Run `embedded-agent.cmd --help` for the complete command surface. Build, flash,
repository mutation, Jenkins, and device commands retain their documented
confirmation gates and path boundaries.

## Modules

`embedded-agent.py` is the stable launcher. Runtime behavior is split into
`embedded_runtime_*.py` modules for CLI, project state, Git, SDK, device,
knowledge, Jenkins, tools, build/flash operations, Aboot, diagnosis, and CAN.
Deploy the complete module set together. `status --json` reports the installed
`platform_version` plus hashes for the entry point and modules so version drift
and partial deployments are observable. Platform version, Capability Contract
version, and command schema versions are separate compatibility axes.

## Test

```powershell
cd runtime\windows\embedded-agent
py -3 -m unittest discover -s tests -v
```

This suite uses fakes and closed confirmation gates. It does not build, call
Jenkins, flash hardware, or transmit CAN frames.
