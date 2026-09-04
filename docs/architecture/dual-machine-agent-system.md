# 主机拓扑与能力路由

本文保留原文件路径，用于兼容已有链接。平台的上位架构见
[Embedded Agent Platform 能力模型](platform-capability-model.md)。双机是可选部署拓扑，
不是固定的 Agent 职责模型。

## 适用场景

当当前任务缺少 Windows 工具链、Jenkins 凭据或已连接设备时，可以把对应工作路由到
Windows/WSL。典型拓扑如下：

```text
当前 Codex 任务
  -> 远程 Windows/WSL Codex 任务（可选）
  -> Windows Native Runtime（按能力需要）
  -> Keil / Jenkins / J-Link / CAN / ADB / 设备
```

当前任务也可以直接运行在 Windows/WSL，并拥有需求、架构、实现和验证的完整生命周期。
此时不需要 Mac 主任务充当永久控制面。Mac 同样可以在本机能力充分时独立完成项目。

## 路由原则

按能力路由，不按主机名称分工：

| 需要的能力 | 推荐位置 |
| --- | --- |
| 需求澄清、架构设计、源码实现、审查 | 任意拥有项目和任务契约的 Codex 任务 |
| 本地测试和文档 | 当前具备依赖的主机 |
| Keil、Windows SDK 或原生驱动 | Windows Native Runtime |
| Jenkins 鉴权、触发和证据 | Windows Native Runtime |
| J-Link、CAN、ADB 和物理设备 | 连接设备的 Runtime Adapter |
| 跨工作区源码同步 | Git branch + exact Commit SHA |

远程 Codex 任务是用户可见、可继续对话的项目任务。Runtime Job 是无推理能力的持久
操作。原生子代理是当前任务内的临时协作者。三者的所有者和生命周期不同，不能混用。

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
  - active Trellis task
  - matching Spec and Knowledge
definition_of_done:
  - 检查命令和退出码
  - 日志或首个失败点
  - 制品元数据和哈希（如适用）
```

远程任务可以从架构设计开始，也可以接手完整项目。委派消息必须明确这种所有权，不能把
远程任务默认限制为编译或 Runtime 操作员。

## 源码和工作区

同一工作区同时只允许一个 writer。正式跨工作区同步使用：

```text
owner workspace commit
  -> push/fetch
  -> target workspace checkout exact SHA
  -> verify clean
```

不得覆盖脏工作区，不使用隐式合并的 `git pull`，不把递归 SCP 当作长期源码同步方案。
只读检查和一次性部署传输不改变 Git 源码真相。

## Runtime Interface

Windows Native Runtime 是深模块。上层只使用固定项目级 Interface，Runtime 内部封装：

- Windows 路径、编码、进程和工具发现。
- Keil、J-Link、Jenkins、ADB、CAN 和 SDK Adapter。
- 操作 Gate、路径约束和凭据隔离。
- 持久 Job、日志、首个失败点和制品哈希。
- 结构化 JSON 和可恢复的错误状态。

Runtime 不接受任意 shell 作为公共 Interface。Runtime 不决定项目架构，也不限制调用它的
Codex 任务只能承担执行工作。

WSL 使用 `runtime/wsl/bin/embedded-agent` 调用固定的 Windows Python 入口。Adapter 只编码
参数数组并转发，不通过 WSL 重新实现构建、Jenkins 或设备操作。

## Jenkins 与设备

Jenkins 的鉴权、参数读取、触发、等待、状态和日志统一由 Runtime `jenkins` 命令执行。
浏览器、直接 HTTP、临时脚本和旧登录辅助程序不作为降级路径。Runtime 不可用时返回
结构化阻塞。

烧写、复位、签名、发布、生产任务和不可逆硬件操作必须通过对应 Gate。跨主机路由不会
继承或扩大授权。

## 证据

任务所有者按声明层级验收：

- 源码：Git 状态、差异、Commit 和活动目标证据。
- 静态或单元测试：命令、退出码和失败点。
- 主机构建：Target、日志、成功标记和新制品。
- CI：Job、Build、参数来源、结果和有界日志。
- 硬件：设备标识、固件来源、操作记录和运行证据。

一个层级通过不能代替其他层级。远程任务返回摘要和证据引用，最终结果所有者仍需按原
验收标准复核。

## 失败恢复

| 失败 | 处理 |
| --- | --- |
| 目标主机不可用 | 保留任务契约，报告连接层阻塞 |
| Runtime `status` 失败 | 修复部署或停止，不绕过 Runtime |
| 目标工作区脏或分歧 | 返回 Git 证据，由所有者决定处理方式 |
| Runtime Job 超时 | 使用 Job ID 恢复状态和增量输出 |
| 任务所有权不明确 | 在写入前补全 owner、范围和完成标准 |

恢复沿原 Interface 进行。拓扑变化不改变任务目标、安全 Gate 或证据要求。
