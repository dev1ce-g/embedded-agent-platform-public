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
  embedded-agent.cmd
  config.example.ps1
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
| `EMBEDDED_JENKINS_SERVER` | Jenkins base URL; there is no built-in endpoint |
| `EMBEDDED_JENKINS_CONFIG` | Local credential/config file; never commit it |
| `EMBEDDED_ABOOT_ROOT` | Installed Aboot tool directory |
| `EMBEDDED_FIRMWARE_ROOT` | Approved local firmware/package root |
| `EMBEDDED_CONTROLCAN_DLL` | ControlCAN vendor DLL |
| `EMBEDDED_ZCANPRO_DLL` | ZCANPro vendor DLL |
| `EMBEDDED_CAN_PYTHON` | Optional vendor-compatible Python executable |

The Runtime otherwise stores mutable state under
`%LOCALAPPDATA%\EmbeddedAgentPlatform\state` and uses install-relative backend
paths. These defaults can be overridden with `EMBEDDED_AGENT_INSTALL_ROOT`,
`EMBEDDED_AGENT_ROOT`, and `EMBEDDED_AGENTCTL`.

## Use

```powershell
embedded-agent.cmd status --json
embedded-agent.cmd project discover --project demo --workspace C:\work\demo --json
embedded-agent.cmd build --project demo --target keil --json
embedded-agent.cmd can driver-list --json
```

Run `embedded-agent.cmd --help` for the complete command surface. Build, flash,
repository mutation, Jenkins, and device commands retain their documented
confirmation gates and path boundaries.

## Modules

`embedded-agent.py` is the stable launcher. Runtime behavior is split into
`embedded_runtime_*.py` modules for CLI, project state, Git, SDK, device,
knowledge, Jenkins, tools, build/flash operations, Aboot, diagnosis, and CAN.
Deploy the complete module set together. `status --json` reports hashes for the
entry point and modules so partial deployments are observable.

## Test

```powershell
cd runtime\windows\embedded-agent
py -3 -m unittest discover -s tests -v
```

This suite uses fakes and closed confirmation gates. It does not build, call
Jenkins, flash hardware, or transmit CAN frames.
