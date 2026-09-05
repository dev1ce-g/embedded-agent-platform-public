# 移除 Trellis 的平台重构方案

## 目标

把仓库从“基于 Trellis 的嵌入式研发预设”重构为模型无关的上下文平面与受控能力平面。
模型或 Agent 负责理解、规划和推理；平台只负责提供可信项目事实、长期规则与知识、固定工具、
副作用门禁和可审计证据。

保留的资产包括项目 Discovery、嵌入式工程规则、Windows 工具 Adapter、持久 Job、Gate 和
Evidence。移除的假设包括工作流状态机、任务仓库、模型专用 Launcher 以及 Trellis 运行时。

## 目标架构

```text
任意 Agent
  -> .embedded-agent/rules、context、knowledge
  -> Capability Contract v1
  -> Local / Windows / WSL / CI / Debug / Device Adapter
```

`.embedded-agent/` 的所有权固定如下：

| 路径 | 所有者 | 策略 |
| --- | --- | --- |
| `manifest.json` | 平台 | 记录投影版本与来源 |
| `rules/platform/` | 平台 | 可刷新、可校验的通用规则 |
| `rules/project/` | 项目 | 不被平台覆盖，可纳入 Git |
| `context/` | Discovery | 自动生成，本地保持，可重复刷新 |
| `knowledge/` | 项目 | 长期知识，不被整体忽略或静默覆盖 |

平台不会创建 workflow、task、hook 或模型配置。

## 实施阶段

| 阶段 | 范围 | 退出条件 | 状态 |
| --- | --- | --- | --- |
| 0 | 固定所有权和投影模型 | `.embedded-agent/` 目录及模型无关术语确定 | 已完成 |
| 1 | 移除活动 Trellis 依赖 | init、refresh、doctor、Discovery、规则和 Runtime 均不需要 Trellis | 已完成 |
| 2 | 安全保留知识 | 提供显式、单向、非破坏迁移；项目规则和知识归项目所有 | 已完成 |
| 3a | 能力边界基础 | 版本化结果/请求 Schema、统一结果信封、类型化 Job 和 reset/write Gate | 已完成 |
| 3b | 有状态能力生命周期 | Catalog、持久 Preflight、作用域 Approval 和终态 Receipt Handler | 计划中 |
| 4 | 公共软件 Golden Path | 空仓库 init → doctor → refresh → doctor，生成确定性上下文且适合 CI | 已完成 |
| 5 | 开源执行 Golden Path | 开源工具链或仿真器完成 build → artifact receipt → run/flash → bounded observation | 计划中 |
| 6 | Adapter 生态 | Manifest、发布 SDK Manager、Fake Target、契约一致性测试和薄 MCP Adapter | 计划中 |
| 7 | 实验室后端 | 在同一契约后评估 OpenOCD、Renode、PlatformIO、Jumpstarter | 计划中 |

`0.2.0` 的发布边界截止到阶段 4。后续阶段是独立、可审查的增量，不作为本发布候选版的阻塞项。
详见[变更日志](../../CHANGELOG.md)、[升级指南](../migration/0.1-to-0.2.zh-CN.md)和
[验收记录](../releases/0.2.0.md)。

## 本次破坏性变更

- `trellis-embedded-init` 替换为 `embedded-project`；
- `trellis-branch` 替换为 `embedded-agent-branch`；
- `marketplace/specs/embedded-dual-machine-v1` 替换为
  `rules/embedded-engineering-v1`；
- 活动项目投影从 `.trellis/` 迁至 `.embedded-agent/`；
- 删除模型专用 Windows Launcher；
- 删除可向任意宿主路径写入的 `knowledge export --to`；在有状态生命周期提供类型化
  产物导出前，使用 `knowledge build --write` 和 `knowledge show`；
- Runtime 结果契约升级到 `1.0.0`。

仓库仍处于 `0.x`，因此本次选择单一清晰架构，不长期维护两套活动执行模型。

## 迁移原则

兼容策略是迁移数据，而不是同时运行两个平台：

- 只有 `embedded-project migrate-trellis` 会读取旧 `.trellis/`；
- 迁移不调用 Trellis，也不删除源目录；
- 旧 workflow、task、hook、agent 和运行会话只报告，不恢复执行状态；
- 项目知识和自有规则按冲突安全方式复制；
- 迁移命令本身跳过 Discovery；随后运行 `init` 或 `refresh`，再运行 `doctor`；
- 不提供双向同步。

详细映射见[迁移指南](../migration/from-trellis.md)。

## 验收条件

1. 活动路径不导入、调用或要求 Trellis；
2. 无 `.trellis/`、无 Trellis 可执行文件的空项目可以初始化；
3. 不生成 workflow/task 目录；
4. 重复 init/refresh 字节稳定，不覆盖项目文件；
5. `rules/project/` 和 `knowledge/` 可由项目自行纳入版本控制；
6. 当前 Runtime 输出 Capability Contract v1 结果信封；尚未接线的生命周期 Schema 明确标为计划；
7. reset、flash、CAN transmit 等外部状态变更默认关闭并要求对应 Gate；
8. Bootstrap 与 Runtime 默认测试通过；
9. 旧名称只存在于显式迁移、防御性排除/诊断、旧入口清理、回归测试和迁移说明中。

## 下一实施切片

下一版本优先提供完全开源、无需私有硬件的执行样例：

```text
discover
  -> preflight
  -> build
  -> artifact hash
  -> simulator run 或显式确认的 flash
  -> bounded log capture
  -> assertion
  -> evidence bundle
```

该样例必须复用现有 Runtime Core 与 Capability Contract，不能再引入第二套执行引擎或模型专用
工作流。

Phase 3b 还必须把当前信任前提变成显式 Preflight 证据：机器管理的可执行文件身份、Keil
Hook/输出路径审查，以及 MPU Container 隔离（无无关可写挂载、Docker Socket、Privileged、
Host Namespace、额外设备或 Capability）。
