# Windows Runtime 源码与运行资产

本文记录 Windows 部署与本仓库的所有权关系，不记录具体机器路径、凭据内容、项目业务日志
或机器私有配置。

## 源码真相

GitHub 仓库是可复用源码和文档的唯一真相。Windows 目录是部署位置，不是独立开发
仓库。正式映射如下：

| 仓库路径 | Windows 部署路径 | 内容 |
| --- | --- | --- |
| `runtime/windows/bin/` | `<install-root>\bin\` | Python 后端和兼容入口 |
| `runtime/windows/embedded-agent/` | `<install-root>\embedded-agent\` | Runtime Core、测试和 README |
| `runtime/windows/can-runtime/` | `<install-root>\can-runtime\` | CAN 依赖清单和安装器 |
| `runtime/windows/*-connections.example.json` | `<install-root>\` | Jenkins/Aboot 机器绑定模板 |
| `VERSION` | `<install-root>\VERSION` | 已部署平台版本 |

部署文件有修改时，先回收到本仓库，再测试、提交和重新部署。不要把 Windows 部署目录
作为长期源码分支。

## 当前 Runtime

实际安装后的 `status --json` 同时报告 `platform_version`、Capability Contract 版本与
关键源码哈希。三者是不同的兼容轴；平台版本来自安装根的 `VERSION`。Windows 和 WSL 入口
不依赖作者机器上的历史路径或备份文件名。

当前受控能力包括项目发现、Git、SDK 映射/命令表面、构建、Jenkins、日志、J-Link、ADB、
Aboot、CAN、持久 Job、Gate 和结构化证据。Runtime-owned SDK Manager 尚未随仓库发布，
因此依赖它的 SDK 查询/拉取能力会 fail closed。CAN Runtime 使用分离的 x86/x64 Python
依赖目录，以支持不同位数的驱动 DLL。

## 不进入 Git 的运行资产

以下内容由机器运行时拥有，不上传 GitHub：

- `credentials/`、`jenkins-connections.json`、`aboot-connections.json`、
  `can-drivers.json` 和任何 token、password、cookie 或私钥。
- `projects/`、`jobs/`、`logs/` 和业务证据。
- `site-packages-x86/`、`site-packages-x64/`、wheelhouse 和 `__pycache__/`。
- `backups/`、`*.bak-*`、`*.next`、`*.orig`、`*.swap-*` 和临时 `_fetch_*.py`。
- 项目专用画像、设备日志、构建制品和业务源码副本。

Windows 的 `agents/` 角色 Markdown 属于历史机器配置，不作为 Platform Core 源码。需要
长期复用的 Agent 行为应写入项目 `AGENTS.md`、Engineering Rule 或专用 Skill。

## 部署检查

部署后至少执行：

1. 运行 `embedded-agent status --json`，确认 contract 和关键源码哈希。
2. 对修改的 Runtime 命令运行对应单元测试或无副作用自检。
3. 对部署文件比较本机和 Windows SHA-256。
4. 将构建、CI、烧写和设备验证分别报告，不用其中一层代替其他层。

整理 Windows 目录时，只删除已确认的历史文件。`credentials/`、项目状态、Job、日志和
制品需要遵循各自保留策略，不因源码归档而删除。
