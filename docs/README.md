# 文档地图

当前 `main` 已经从活动架构中移除 Trellis：模型或 Agent 负责推理和任务编排，平台负责
项目上下文、工程规则、受控能力、门禁、持久状态与证据。`release/0.2.0` 保留为本次
重构的软件验收分支；正式版本尚未创建 tag 或 GitHub Release。

## 当前架构

- [平台能力模型](architecture/platform-capability-model.md)：模型、平台与主机能力的所有权。
- [项目投影与上下文](architecture/project-projection-and-context.md)：`.embedded-agent/`、
  Rule Pack、Discovery、知识索引与 Bootstrap 行为。
- [双机 Agent 系统](architecture/dual-machine-agent-system.md)：可选部署拓扑；不再固定
  Mac 规划、Windows 执行，也允许任一 Agent 承担完整生命周期。
- [Capability Contract](../contracts/README.md)：请求、结果、Job、Gate 与 Evidence 的
  稳定数据边界。
- [工程规则包](../rules/README.md)：模型无关的嵌入式工程规则入口。

## 接入与运维

- [仓库首页](../README.zh-CN.md)：安装、初始化、Runtime 配置与安全边界。
- [Windows Runtime 资产](operations/windows-runtime-assets.md)：安装目录、机器配置和
  第三方工具边界。
- [0.2.0 软件验收](releases/0.2.0.md)：实际运行的测试、通过的 CI 与明确未覆盖项。

## 从 Trellis 迁移

- [0.1 到 0.2 升级指南](migration/0.1-to-0.2.zh-CN.md)：破坏性变更与升级步骤。
- [旧数据映射](migration/from-trellis.md)：显式、单向、非破坏迁移规则。
- [重构记录](refactoring/trellis-removal.zh-CN.md)：已完成阶段与后续路线。

上述文档中的 Trellis 只表示旧架构、迁移来源或兼容清理对象。现行项目入口是
`embedded-project`，活动投影是 `.embedded-agent/`，通用规则位于 `rules/`；平台不运行
旧 workflow、task、hook、agent 或 Trellis CLI。

`docs/research/` 是方案调研和外部项目评估，不定义现行平台契约；出现差异时，以当前架构、
Contract、Rule Pack、代码和测试为准。
