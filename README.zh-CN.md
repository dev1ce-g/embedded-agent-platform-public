# Embedded Agent Platform

[English](README.md) | [简体中文](README.zh-CN.md)

面向存量、异构嵌入式工程的模型无关上下文与能力控制平面。模型或 Agent 负责推理，平台负责
提供项目事实、工程规则、受控工具、安全门禁、持久 Job 和可审计证据。

平台不是工作流引擎，也不要求或启动某个指定模型。Codex、Claude、OpenCode 或其他 Agent
都可以通过 CLI、Skill 或后续协议 Adapter 使用同一套项目上下文和 Runtime Interface。

当前状态：**`0.2.0` 发布候选版**，尚未创建正式 tag。接入前请审阅
[变更日志](CHANGELOG.md)、[从 `0.1` 升级到 `0.2`](docs/migration/0.1-to-0.2.zh-CN.md)和
[软件验收边界](docs/releases/0.2.0.md)。

## 仓库结构

```text
rules/           可复用嵌入式工程规则包
contracts/       能力请求与结果契约
skills/          感知 Runtime contract 的模型可移植 Skill
bootstrap/       项目投影、Discovery、迁移和测试
runtime/mac/     macOS/Linux 连接 Windows Runtime 的 SSH 传输 Adapter
runtime/wsl/     WSL 到 Windows 的互操作 Adapter
runtime/windows/ Windows Runtime 与工具/硬件 Adapter
docs/            架构、迁移和运维文档
```

整体边界见[平台能力模型](docs/architecture/platform-capability-model.md)和
[项目投影模型](docs/architecture/project-projection-and-context.md)。已执行的重构步骤与后续路线见
[Trellis 移除与平台重构](docs/refactoring/trellis-removal.zh-CN.md)。

## 项目上下文

初始化只创建上下文投影，不创建强制任务或工作流：

```text
.embedded-agent/
  manifest.json     平台管理的投影元数据
  rules/platform/  平台管理的通用工程规则
  rules/project/   项目自有规则或覆盖项
  context/         自动生成的项目与 Target 事实
  knowledge/       项目所有的长期知识
  evidence/        可选的本地 Runtime/Adapter 证据缓存
```

平台规则和生成上下文默认保持本地；项目规则和知识不会被整体排除，项目可以将其纳入 Git，
也可以让 Agent 直接引用已有文档或独立知识库。

## 快速开始（macOS、Linux 或 WSL）

安装本地项目与分支策略工具、当前主机 Adapter 和仓库内 Skill（`embedded-project`、
`embedded-agent-branch` 与 `embedded-agent`）：

```bash
./install.sh
```

安装器创建的是指向当前 checkout 的链接，因此请保留该 checkout。命令默认安装到
`~/.local/bin`，请确认它位于 `PATH`：

```bash
export PATH="${HOME}/.local/bin:${PATH}"
```

可以用
`EMBEDDED_PLATFORM_BIN_DIR` 修改命令目录，用 `EMBEDDED_PLATFORM_SKILL_DIR` 修改 Skill
目录。

无需 Trellis 或模型专用 CLI 即可完成项目接入：

```bash
embedded-project init /path/to/project --discovery local --json
embedded-project doctor /path/to/project --json
embedded-project refresh /path/to/project --discovery local --json
```

需要 Windows 能力时，先配置传输并验证 Runtime 可达。macOS 或 Linux 通过 SSH 使用：

```bash
export EMBEDDED_AGENT_HOST='<ssh-host-alias>'
export EMBEDDED_AGENT_REMOTE_PREFIX='C:\Users\<user>\AppData\Local\EmbeddedAgentPlatform'
embedded-agent status --json
```

WSL 则将 `WSL_EMBEDDED_AGENT_PREFIX` 指向挂载后的 Windows 安装根目录，并执行同一条
status 检查。通过后再显式登记稳定项目 ID 和真实工作区：

```bash
embedded-project init /path/to/project \
  --project-id <project-id> \
  --windows-workspace '<windows-workspace>' \
  --build-knowledge \
  --json
```

Windows 工作区必须位于 Runtime 主机配置的 `EMBEDDED_AGENT_WORKSPACE_ROOT` 下。

Bootstrap 只执行投影、只读 Discovery、Runtime 状态检查和可选 Knowledge Build；不会构建、
烧写、复位、触发 CI 或操作设备。

## Windows Runtime

需要 Python 3.9 或更高版本：

```powershell
git clone https://github.com/dev1ce-g/embedded-agent-platform-public.git
cd embedded-agent-platform-public
py -3 runtime\windows\install.py
& "$env:LOCALAPPDATA\EmbeddedAgentPlatform\embedded-agent.cmd" status --json
```

Keil、J-Link、Aboot、CAN 厂商工具等不会随仓库分发。Mac 与 WSL Adapter 只转发参数数组，
不会复制 Runtime 的门禁和业务逻辑。

## 迁移已有项目

迁移必须显式执行，并且是单向、非破坏的：

```bash
embedded-project migrate-trellis /path/to/project --dry-run --json
embedded-project migrate-trellis /path/to/project --json
embedded-project init /path/to/project --discovery local --json
embedded-project doctor /path/to/project --json
```

迁移器只导入项目上下文、知识和项目自有规则；不会调用 Trellis、删除 `.trellis/`，也不会
把旧 workflow、hook、agent 或 task 恢复成活动平台状态。迁移命令跳过 Discovery，因此随后
必须执行 `init`（或 `refresh`）和 `doctor`；权威工具链事实位于 Windows 时应使用 Windows
Discovery。详见
[迁移指南](docs/migration/from-trellis.md)。

## 安全与测试

修改仓库、CI 或设备状态的 Runtime 操作必须使用固定命令和显式 Gate。不要提交凭据、私钥、
项目源码副本、设备日志、生成上下文或受许可限制的厂商二进制文件。

```bash
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s bootstrap/tests -v

cd runtime/windows/embedded-agent
PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache \
  python3 -m unittest discover -s tests -v
```

硬件、Jenkins、签名、烧写和设备测试需要显式配置与授权，默认不会执行。

需要可复现部署时，应从已审阅的精确 commit 安装；正式发布后固定使用 `v0.2.0`，不要让
部署持续跟随变化中的 `main`。

开发检查见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题请按
[SECURITY.md](SECURITY.md) 私下报告。

本项目采用 [Apache License 2.0](LICENSE) 开源许可证。
