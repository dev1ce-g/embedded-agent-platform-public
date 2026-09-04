# Embedded Agent Platform 能力模型

本文定义平台的稳定架构。平台面向嵌入式项目的完整生命周期，不把某台主机固定为
「规划端」或「执行端」。Mac、WSL、Windows 或其他已连接主机上的 Codex 任务，只要具备
所需仓库、工具和授权，都可以从需求澄清、架构设计开始接手项目，并持续完成实现、验证
和交付。

## 核心模型

```text
项目目标与授权
  -> Trellis 工作流和任务契约
  -> Embedded Platform Core
       - 项目发现与活动目标证明
       - 架构、状态和安全规则
       - 实现、审查与验证流程
       - 证据和交付契约
  -> Capability Adapter
       - 本地仓库与本地工具
       - Windows Native Runtime
       - WSL/Windows 互操作
       - 远程 Codex 任务
       - CI、调试器和设备
```

平台核心提供稳定的工程语义。主机、传输方式和工具链是可替换的 Adapter。任务根据能力
选择 Adapter，不根据主机名称预先分配角色。

## Agent 所有权

一个 Codex 任务可以拥有完整项目，也可以只承担有界子任务。所有权由当前任务契约决定：

- 完整项目所有者负责需求、架构、计划、实现、验证和最终结论。
- 委派只转移明确结果及其允许的写入范围，不默认转移最终决策权。
- 任务可以在同一主机完成全部工作，也可以按工具、设备或上下文需要跨主机路由。
- 同一工作区同时只允许一个 writer。并行实现使用独立 worktree 或独立工作区。
- 任务位置不会扩大授权。烧写、复位、签名、发布和生产操作仍需各自的 Gate。

Mac 编排、Windows 编译是受支持的部署拓扑，但不是平台的固定职责模型。Windows Codex
任务可以直接创建 Trellis task、完成架构设计和修改源码；Mac Codex 任务也可以在本机
工具满足要求时完成实现与验证。

## Platform Core

Platform Core 是深模块。它通过较小的 Interface 提供以下能力：

- 将自然语言需求转为明确的目标、非目标、约束、授权和验收标准。
- 证明活动工程、Target、SDK、配置、调用链和制品来源。
- 路由命中的嵌入式 Spec，并维护项目事实、推断和待确认项。
- 保护状态所有权、并发、生命周期、协议、硬件和安全约束。
- 按风险选择静态检查、单元测试、主机构建、CI 或硬件验证。
- 保存命令、退出码、首个失败点、日志、制品哈希和未覆盖风险。

项目 Agent 面向这个 Interface 工作，不复制 Keil、J-Link、Jenkins、ADB、CAN 或不同
操作系统的实现细节。

## Capability Adapter

Adapter 只处理特定环境中的差异：

| Adapter | 适用能力 | 约束 |
| --- | --- | --- |
| Local | 本地源码、测试、文档和本地工具 | 服从项目规则和工作区状态 |
| Windows Native Runtime | Keil、J-Link、CAN、ADB、Jenkins、SDK 和设备 | 固定命令、Gate、JSON 和证据 |
| WSL interop | 从 WSL 使用 Windows Native Runtime | 保持 Runtime contract，不重写业务逻辑 |
| Remote Codex task | 把有界结果交给另一主机或项目任务 | 消息自包含，一个工作区一个 writer |
| Git synchronization | 在多个工作区之间传递源码状态 | branch/commit SHA 明确，禁止覆盖脏工作区 |

Windows Native Runtime 封装 Windows 路径、编码、进程位数、凭据、工具发现和设备访问。
只有任务需要这些能力时才加载对应 Spec 和 Runtime；本地架构设计、代码审查或无需
Windows 工具的实现不应被强制路由到 Windows。

## Trellis 工作流

Trellis 工作流保持主机无关：

1. Intake：冻结目标、授权、非目标和验收标准。
2. Discover：确认活动仓库、工程、Target、工具链和项目规则。
3. Design：记录架构决策、状态所有权、接口和验证策略。
4. Implement：在唯一 writer 工作区完成最小充分改动。
5. Verify：按行为风险取得对应层级的实际证据。
6. Deliver：提交可审查差异，记录已验证和未验证内容。

跨主机只是某一步的能力路由。任务不应因为切换主机而重新开始需求或架构阶段，也不应
把 Runtime Job、Codex 子代理和用户可见的远程 Codex 任务混为同一种对象。

## 完成标准

平台变更完成时，应能回答：

- 哪个任务拥有最终结果，哪些工作被委派。
- 哪个工作区和 Commit 是源码真相。
- 使用了哪些 Adapter，以及选择原因。
- 每个声明对应什么验证证据。
- 哪些风险未覆盖，恢复或继续路径是什么。

具体 Windows 拓扑见 [主机拓扑与能力路由](dual-machine-agent-system.md)。Windows 部署
内容见 [Windows Runtime 源码与运行资产](../operations/windows-runtime-assets.md)。
