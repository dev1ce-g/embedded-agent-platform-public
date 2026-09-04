# Embedded Agent Platform

[English](README.md) | [简体中文](README.zh-CN.md)

面向嵌入式开发的可复用 Trellis Spec、项目接入工具和受控 Runtime Adapter。平台通过有边界的
JSON 命令接口接入特定主机上的工具链、CI 服务和硬件，不把单台机器的目录作为公共契约。

## 仓库内容

```text
marketplace/     可复用的嵌入式平台 Spec
skills/          感知 Runtime contract 的 Agent Skill
bootstrap/       项目初始化、Discovery 和测试
runtime/mac/     连接 Windows Runtime 的 SSH 客户端
runtime/wsl/     WSL 互操作客户端
runtime/windows/ Windows Runtime 与工具/硬件 Adapter
docs/            架构和运维文档
```

架构与信任边界见[平台能力模型](docs/architecture/platform-capability-model.md)和
[主机拓扑](docs/architecture/dual-machine-agent-system.md)。

## 快速开始

克隆或下载仓库即可，不要求使用仓库作者的目录结构。

### Windows 本地 Runtime

需要 Python 3.9 或更高版本。

```powershell
git clone https://github.com/your-organization/embedded-agent-platform.git
cd embedded-agent-platform
py -3 runtime\windows\install.py
& "$env:LOCALAPPDATA\EmbeddedAgentPlatform\embedded-agent.cmd" status --json
```

通过 `--prefix C:\Your\Install\Directory` 可指定安装目录。重复运行安装器会更新受管源码，
并保留独立的 `state` 目录。按需复制并修改生成的 `config.example.ps1`。Keil、J-Link、
Aboot、CAN 厂商工具等外部软件不会随仓库分发。

### Mac 或 WSL 客户端

```bash
./install.sh
```

Mac 客户端需要 SSH 主机和 Windows 安装目录：

```bash
export EMBEDDED_AGENT_HOST='windows-host'
export EMBEDDED_AGENT_REMOTE_PREFIX='C:\Users\you\AppData\Local\EmbeddedAgentPlatform'
embedded-agent status --json
```

WSL 客户端使用对应的 WSL 路径：

```bash
export WSL_EMBEDDED_AGENT_PREFIX='/mnt/c/Users/you/AppData/Local/EmbeddedAgentPlatform'
embedded-agent status --json
```

## 初始化项目

```bash
trellis-embedded-init /path/to/project --discovery local
```

接入脚本从当前检出的版本安装 Spec，并保留项目已有内容。Windows 项目需要显式注册真实工作区：

```bash
trellis-embedded-init /path/to/project \
  --project-id <project-id> \
  --windows-workspace '<windows-workspace>' \
  --build-knowledge
```

项目工作区、构建工具、Jenkins 地址和凭据、Aboot 工具、固件包及 CAN 厂商库均属于本地配置。
支持的环境变量见 [`runtime/windows/config.example.ps1`](runtime/windows/config.example.ps1)。

## 安全边界

Bootstrap 不会构建、烧写、复位、采集 RTT、操作设备或修改凭据。Runtime 中会修改仓库或设备
状态的命令具有显式确认 Gate。请勿提交凭据、私钥、项目源码、设备日志、生成的项目画像或
受许可限制的厂商二进制文件。

## 测试

```bash
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s bootstrap/tests -v

cd runtime/windows/embedded-agent
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s tests -v
```

GitHub Actions 会在 Ubuntu 和 Windows 上运行 Runtime 测试。硬件、Jenkins、签名、烧写和设备
测试需要显式配置环境，默认不会执行。

## 贡献与安全

开发检查见 [CONTRIBUTING.md](CONTRIBUTING.md)，私下报告漏洞的方式见 [SECURITY.md](SECURITY.md)。

本项目采用 [Apache License 2.0](LICENSE) 开源许可证。
