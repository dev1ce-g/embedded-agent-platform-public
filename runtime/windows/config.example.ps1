# Copy the settings you need into your PowerShell profile or CI environment.
# Keep credentials outside this repository.

$env:AGENTCTL_UV4_PATH = 'C:\Keil_v5\UV4\UV4.exe'
$env:AGENTCTL_JLINK_PATH = 'C:\Program Files\SEGGER\JLink\JLink.exe'
$env:EMBEDDED_AGENT_WORKSPACE_ROOT = "$env:LOCALAPPDATA\EmbeddedAgentPlatform\workspaces"

# Optional integrations:
# Jenkins endpoints and credential files are bound in the machine-owned
# jenkins-connections.json next to embedded-agent.cmd. Its path is not selected
# through task environment or CLI input; callers choose only a connection id.
# $env:EMBEDDED_SDK_STORE = 'C:\SDKs'
# Aboot tool and firmware roots are not task environment settings. Copy
# aboot-connections.example.json to aboot-connections.json next to
# embedded-agent.cmd and pin adownload.exe with its SHA-256.
# CAN vendor DLLs are intentionally not configurable through task environment
# variables. Copy can-runtime\can-drivers.example.json to can-drivers.json next
# to embedded-agent.cmd, then edit that machine-owned file.
# $env:AGENTCTL_MPU_CONTAINER = 'embedded-build'
# $env:AGENTCTL_MPU_WORKDIR = '/home/project/mpu/project/cmake'
# $env:AGENTCTL_MPU_SDK_PATH = '/home/ql-sdk'
# $env:AGENTCTL_MPU_ARTIFACT_PATH = '/home/build/target'
