# 主机拓扑与能力路由

双机只是可选部署拓扑，不是固定的 Agent 职责模型。上位架构见
[平台能力模型](platform-capability-model.md)。

## 适用场景

当当前 Agent 缺少 Windows 工具链、CI 凭据或已连接设备时，只把对应能力路由到
Windows/WSL Runtime：

```text
当前 Agent
  -> 可选的远程 Agent
  -> Windows Native Runtime
  -> Keil / Jenkins / J-Link / CAN / ADB / 设备
```

Agent 也可以直接运行在 Windows/WSL，并拥有需求、架构、实现和验证的完整生命周期。Mac、
Windows、WSL 或 Linux 描述能力位置，不预设规划端和执行端。

## 路由原则

| 需要的能力 | 推荐位置 |
| --- | --- |
| 需求、架构、源码实现、审查 | 任意拥有项目上下文和授权的 Agent |
| 本地测试和文档 | 当前具备依赖的主机 |
| Keil、Windows SDK、原生驱动 | Windows Native Runtime |
| Jenkins 鉴权、触发和证据 | Windows Native Runtime |
| J-Link、CAN、ADB、物理设备 | 连接资源的 Runtime Adapter |
| 跨工作区源码同步 | Git branch + exact Commit SHA |

远程 Agent 是具有推理能力的协作者；Runtime Job 是无推理的持久操作；临时子 Agent 是当前
任务内的有界委派。三者的所有者、写入权限和生命周期不能混用。

## 委派契约

跨主机委派至少包含：

```yaml
objective: 一个可验证结果
owner: 最终结果所有者
repository: remote + branch + exact_commit_sha
workspace: 目标工作区
allowed_write_paths:
  - 允许修改的路径
forbidden_actions:
  - 未授权提交、推送、烧写、签名、发布和生产操作
required_context:
  - AGENTS.md
  - .embedded-agent/context/project-profile.json
  - matching rules and knowledge
definition_of_done:
  - 检查命令和退出码
  - 日志或首个失败点
  - 制品元数据和哈希（如适用）
```

委派可以只请求一个结果，也可以显式转移完整项目所有权。主机位置不会自动扩大权限。

## 源码和工作区

同一工作区同时只允许一个 writer。正式跨工作区同步使用：

```text
owner workspace commit
  -> push/fetch
  -> target workspace checkout exact Commit SHA
  -> verify clean
```

不得覆盖脏工作区，不使用隐式合并的 `git pull`，不把递归复制当作长期源码同步合同。

## Runtime Interface

Windows Native Runtime 封装：

- Windows 路径、编码、进程架构和工具发现；
- Keil、J-Link、Jenkins、ADB、CAN、Aboot，以及当前 fail-closed 的 SDK
  映射/命令表面（Runtime-owned SDK Manager 尚未发布）；
- 操作 Gate、路径约束和凭据隔离；
- 持久 Job、日志、首个失败点和制品哈希；
- Capability Contract v1 结构化结果。

Runtime 不接受任意 shell，不决定项目架构，也不启动特定模型。WSL 和 Mac Adapter 只转发
参数数组，不重写 Runtime 的业务逻辑或 Gate。

## 证据与恢复

源码、静态检查、主机构建、CI、烧写和运行行为是独立证据层。一个层级通过不能代替其他
层级。

| 失败 | 处理 |
| --- | --- |
| 目标主机不可用 | 保留任务目标，报告连接层阻塞 |
| Runtime `status` 失败 | 修复部署或停止，不绕过 Runtime |
| 工作区脏或分歧 | 返回 Git 证据，由结果所有者决定 |
| Runtime Job 超时 | 使用 Job ID 恢复状态和增量输出 |
| 所有权或 Gate 不明确 | 在写入和外部状态变更前补全 |

恢复沿原 Capability Interface 进行。拓扑变化不改变任务目标、安全 Gate 或证据要求。
