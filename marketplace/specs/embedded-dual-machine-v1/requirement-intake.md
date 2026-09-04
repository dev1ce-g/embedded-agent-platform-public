# Requirement Intake Rules

当用户描述新需求、bug 或功能请求时，Agent 必须按照本规则结构化输入，
而不是直接开始编码或在聊天中零散收集信息。

## 1. 触发条件

以下任一情况触发 requirement intake 流程：

- 用户在 `/trellis:start` 后描述一个新需求
- `trellis-brainstorm` skill 被触发
- 用户描述涉及多个模块/边界，且缺乏清晰的问题定义
- 用户明确请求创建新 task

## 2. Agent 行为

### 2.1 判断复杂度

Agent 首先根据用户描述判断走 Quick Intake 还是 Full Intake：

| 信号 | 走向 |
|------|------|
| 单文件、参数配置、明确的小改动 | Quick Intake |
| 多模块、跨 ECU、协议、安全、bug 排查 | Full Intake |
| 不确定 | Full Intake（宁可多问，不可遗漏） |

### 2.2 引导填写

Agent 使用 `.trellis/spec/requirement-intake-template.md` 作为交互指南：

1. **不要求用户逐节填写模板**。用户自然语言描述即可。
2. **Agent 主动提取**：从用户描述中抽取标题、目标、模块、边界。
3. **Agent 主动追问缺失信息**，按优先级：

   优先级 1（嵌入式领域最关键，优先问）：
   - 复现环境（台架/实车/单板，硬件版本）
   - 是否涉及协议/通信 → 追问 CAN ID、信号级细节
   - 代码层边界（自研 vs 供应商 vs AUTOSAR 生成）

   优先级 2（帮助缩小范围）：
   - 上次正常是什么时候（回归上下文）
   - 症状时间线
   - 涉及模块（不要求精确，AI 会补全）

   优先级 3（帮助验证设计）：
   - 期望的验证方式
   - 已知约束

4. **Agent 主动索要资产**：
   - 涉及多模块 → 问 topology 图
   - 涉及时序 → 问 sequence 图或时间线
   - 涉及 CAN/网络 → 问 `.cap` 抓包
   - 涉及异常日志 → 问 serial log

### 2.3 结构化输出

Agent 将收集到的信息编译为 `context.generated.yaml`，放入对应 task 目录：
`.trellis/tasks/<task-slug>/context.generated.yaml`

输出必须包含：

```yaml
task:
  name: <task-slug>
  title: <人类可读标题>
  channel: quick | full

boundary:
  - type: <boundary-type>
    confidence: high | medium | low
    source: <从哪条用户输入推断>

ownership:
  <component>: MCU | MPU | both

sequence:
  - <step>
  - <step>

knowledge:
  - .trellis/spec/<file>.md
  - .trellis/knowledge/<path>/<file>.md

skills:
  - <matching-skill-name>

risk:
  - type: <risk-type>
    severity: high | medium | low
    reason: <一句话原因>

verify:
  - item: <检查项>
    method: <如何检查>

ambiguities:
  - question: <待确认的问题>
    need: <需要什么信息来解决>
    impact: <不确认的话有什么后果>
```

### 2.4 置信度标注（关键）

每个 AI 推断的条目必须附置信度。人类 review 时优先关注 `medium` 和 `low` 条目。

- `high`：用户明确说明，或代码/文档中有明确证据。
- `medium`：从上下文推断，但用户未直接确认。
- `low`：AI 猜测，需要用户确认才可进入 implement 阶段。

**禁止**：把 medium/low 置信度的 boundary/ownership 直接当作事实用于 job-packet 签发。

### 2.5 追问上限

一次交互中追问不超过 5 个问题。优先问优先级 1。

## 3. 输出对接

编译完成后，`context.generated.yaml` 的内容自动注入 Trellis 任务上下文：

```text
context.generated.yaml
    ↓
├── implement.jsonl   ← boundary + knowledge + skills
├── check.jsonl       ← verify checklist
└── job-packet.md     ← 双机执行时需要的 required_context + commands
```

双机执行的 `job-packet.md` 至少应包含：

- `source_of_truth: windows`
- Windows 原生 `workspace`
- 可选 SMB observation path，并标注 read-mostly
- `execution.mode`，例如 `native-agent` 或 `runtime-wrapper`
- `allowed_write_paths` 与 `forbidden_actions`
- `required_context`、`commands`、`evidence_required`
- `handoff.md` 与 `remote-sessions.jsonl` 输出位置

Agent 应在 `trellis-before-dev` 触发前确认 `ambiguities` 列表已清空（或仅剩不影响实施的 low-impact 条目）。

如果任务涉及多个相似目录、目标、预编译库或参考项目，在进入实现前按
`evidence-first-engineering.md` 完成 Active Target Gate，并把真实生效目标及证据写入
`context.generated.yaml` 的 `boundary` 或任务 Context Packet。目录名不能替代构建或调用链证据。

## 4. 约束

- 不要要求用户手写 YAML 或填表格。Agent 负责把自然语言转成结构。
- 不要在没有 topology/sequence 信息的情况下签发跨模块的 job-packet。
- 不要在 ambiguities 未清空时进入 implement 阶段。
- 不要跳过复现环境确认（嵌入式问题的最常见根因差异）。

## 5. 模板位置

完整交互模板：`.trellis/spec/requirement-intake-template.md`

该模板定义了各字段的详细格式和示例。本 spec 定义 Agent 的行为规则；
模板定义用户交互的具体内容。
