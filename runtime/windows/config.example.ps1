# Copy the settings you need into your PowerShell profile or CI environment.
# Keep credentials outside this repository.

$env:AGENTCTL_UV4_PATH = 'C:\Keil_v5\UV4\UV4.exe'
$env:AGENTCTL_JLINK_PATH = 'C:\Program Files\SEGGER\JLink\JLink.exe'
$env:EMBEDDED_AGENT_WORKSPACE_ROOT = "$env:LOCALAPPDATA\EmbeddedAgentPlatform\workspaces"

# Optional integrations:
# $env:EMBEDDED_JENKINS_SERVER = 'https://jenkins.example.com'
# $env:EMBEDDED_JENKINS_CONFIG = "$env:USERPROFILE\.config\embedded-agent\jenkins.json"
# $env:EMBEDDED_SDK_MANAGER = 'C:\Tools\sdk_manager.py'
# $env:EMBEDDED_SDK_STORE = 'C:\SDKs'
# $env:EMBEDDED_ABOOT_ROOT = 'C:\Tools\aboot'
# $env:EMBEDDED_FIRMWARE_ROOT = 'C:\Firmware'
# $env:EMBEDDED_CONTROLCAN_DLL = 'C:\Program Files\ZLG\ControlCAN.dll'
# $env:EMBEDDED_ZCANPRO_DLL = 'C:\Program Files\ZCANPRO\zlgcan.dll'
# $env:EMBEDDED_CAN_PYTHON = 'C:\Path\To\python.exe'
# $env:AGENTCTL_MPU_CONTAINER = 'embedded-build'
# $env:AGENTCTL_MPU_WORKDIR = '/home/project/mpu/project/cmake'
# $env:AGENTCTL_MPU_SDK_PATH = '/home/ql-sdk'
# $env:AGENTCTL_MPU_ARTIFACT_PATH = '/home/build/target'
