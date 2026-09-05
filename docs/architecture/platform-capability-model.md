# Embedded Agent Platform 能力模型

本文定义平台的稳定边界。平台面向存量和异构嵌入式工程，不把某个模型、工作流、主机或
厂商工具作为核心依赖。

## 核心模型

```text
模型或 Agent
  -> Context Plane
       - Engineering Rules
       - 生成的项目与 Target 事实
       - 项目长期知识
  -> Capability Contract
       - discover / preflight
       - execute / status
       - evidence
  -> Capability Adapter
       - 本地仓库与工具
       - Windows Native Runtime
       - WSL / SSH 传输
       - CI、调试器和实验室设备
```

模型负责理解目标、制定计划和选择能力。平台负责回答三个可验证问题：

1. 当前实际生效的工程、Target、源码和工具链是什么。
2. 当前环境允许执行哪些受控操作，副作用和资源所有权是什么。
3. 每个结果对应哪些命令、日志、制品、设备和源码证据。

当前 Runtime 已接入统一结果信封、类型化持久 Job 和既有操作 Gate；Catalog、持久化
Preflight、作用域化 Approval 与终态 Receipt 仍是下一阶段实现，不应被调用方视为已经可用的
公共命令。

平台不要求模型公开内部思维链，也不把 Intake、Design、Implement 等阶段实现成必须通过的
状态机。

## Context Plane

项目投影位于 `.embedded-agent/`：

| 路径 | 所有者 | 内容 |
| --- | --- | --- |
| `rules/platform/` | 平台 | 当前安装的通用工程规则 |
| `rules/project/` | 项目 | 项目自有约束和规则覆盖 |
| `context/` | Discovery / Bootstrap | 工程、Target、仓库、工具链、能力事实及生成的知识索引 |
| `knowledge/` | 项目 | 经确认的架构、决策、故障和操作知识 |

生成事实必须包含来源和置信度。文档可以被自动索引，但未经确认的推断不能自动升级为项目
规范。Project Rule 与 Knowledge 不由 Bootstrap 静默覆盖。

## Capability Contract

Capability Contract 是平台最稳定的公共边界。调用者只提交有类型的操作和参数，Adapter
返回统一结果与证据，不能传入任意 shell。

完整有状态生命周期的目标请求契约至少声明（Catalog/Preflight/Approval/Receipt Handler
尚未全部接线）：

- operation、capability 和 risk class；
- project/target/artifact 引用（适用时）；
- 有界参数和预期观测；
- 外部状态变更所需确认。

当前已接线的结果信封至少包含：

- contract/schema version、operation、ok、exit code 和时间；
- first failure 或成功标记；
- 项目、Target、源码、工具链与设备身份（适用时）；
- 日志、Job 和制品引用；
- 实际完成的验证层级。

JSON Schema 见 `contracts/`。CLI、Skill、MCP 或其他协议 Adapter 最终都必须进入同一
Runtime Core，不能形成第二套 Gate 与执行逻辑。

## Capability Adapter

| Adapter | 适用能力 | 约束 |
| --- | --- | --- |
| Local | 源码、静态检查、本地测试和文档 | 服从项目规则与工作区状态 |
| Windows Native Runtime | Keil、J-Link、CAN、ADB、Jenkins、设备及 SDK 映射表面 | 固定命令、Gate、JSON 和证据；SDK Manager 尚未发布 |
| WSL / SSH transport | 参数数组跨主机转发 | 不重写 Runtime 业务逻辑 |
| CI / Lab backend | 持久构建、HIL、设备租约 | 明确 Job、资源所有权和超时 |
| Simulator | Renode/QEMU 等虚拟 Target | 不把仿真结果冒充真实硬件证据 |

任务按能力选择 Adapter，不按主机名称预设角色。任何具备仓库、上下文、工具和授权的 Agent
都可以拥有需求、架构、实现、验证和交付。

## 安全与资源

- 同一工作区只允许一个 writer；并行写入使用独立 worktree 或工作区。
- Flash、reset、CAN transmit、NVM/eFuse、签名、发布和生产操作必须显式确认。
- Probe、串口、CAN 通道、DUT 和电源等共享资源应由 Adapter 提供 lease/互斥语义。
- Runtime 失败表示能力不可用，不授权调用方绕过固定 Interface。
- 路径、工具、目标和制品必须先解析为平台已发现的对象，再允许有副作用的操作。

当前机器级工具路径/PATH 由管理员配置并受 ACL 保护；Keil 工程 Hook、项目构建脚本和既有
MPU Builder Container 仍属于可执行的受信输入，并非完整宿主沙箱。在 Phase 3b Preflight
接线前，只登记可信工作区，并使用最小权限 Runtime 账户和没有额外可写宿主挂载、Docker
Socket、Privileged/Host Namespace、额外设备或 Capability 的专用容器。

## 参考工程生命周期

需求澄清、Discover、Design、Implement、Verify、Deliver 是推荐检查视角，不是平台工作流。
模型可以根据任务复杂度合并、回退或跳过不适用阶段，但必须始终满足：

- 写入前知道目标、范围、所有者和禁止动作；
- 改动前证明活动 Target；
- 有副作用操作前通过对应 Gate；
- 交付时逐层陈述实际证据和未验证风险。

## 完成标准

平台变更完成时，应能回答：

- 哪个 Agent、工作区和 Commit 拥有结果。
- 使用了哪些上下文及其来源、版本和新鲜度。
- 调用了哪些 Capability Adapter，风险级别和授权是什么。
- 每个声明对应什么可重放证据。
- 哪些层级未验证，下一步如何恢复或继续。
