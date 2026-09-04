# Embedded Platform Skills

该目录保存与 Embedded Agent Platform Runtime 配套的 Agent Skill。Skill 负责识别意图、
选择固定命令、执行 Gate 和解释结构化证据；`runtime/` 仍是工具执行的唯一实现。

当前提供：

- `embedded-can-runtime`：CAN Driver Adapter 探测、有限时监控、报文发送和 UDS 操作。

Skill 不复制厂商 DLL、机器路径、项目事实或运行状态。安装到 Agent 环境时，复制完整的
Skill 目录，并保持仓库版本为来源。

