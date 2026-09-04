# AI-Native Embedded Requirement Intake Template

在 Trellis 任务工作流（brainstorm → before-dev → implement → check）之前使用。
人类描述问题，AI 负责结构化，人类只修正 AI 的输出。

---

## 快速通道 vs 完整通道

| 通道 | 适用场景 | 使用模板 |
|------|---------|---------|
| Quick Intake | 参数配置、单文件小改、已知模式的修复 | 仅填 1-3 节 |
| Full Intake | 跨模块、跨 ECU、协议、安全、疑难 bug | 完整填写 |

AI 应根据用户描述自动判断复杂度，不确定时走 Full Intake。

---

# Part A: Quick Intake（最小输入）

## 1. 基础信息

```markdown
# Task

标题：[一句话描述]

目标：[要达成什么]

优先级：高 / 中 / 低

涉及文件（如果知道）：
  - path/to/file1.c
  - path/to/file2.h
```

## 2. 问题/需求描述

自由描述，允许口语化。Tell the story:
- 什么现象？
- 什么时候开始？
- 什么情况下触发？

```markdown
# Problem

[自然语言描述]
```

## 3. 约束（如果有）

```markdown
# Constraints

- [ ] 不能修改 generated code
- [ ] 不能修改 vendor SDK
- [ ] 不能影响 OTA
- [ ] 不能影响安全流程
- [ ] 其他：[填写]
```

---

# Part B: Full Intake（完整输入）

以下各节按需填写。AI 发现缺失关键信息时，应主动向用户提问。

## 4. 涉及模块

```markdown
# Related Modules

[勾选或列出涉及的子系统，不要求精确，AI 会补全]

通信/协议：
- [ ] XCU（MCU/MPU 通信）
- [ ] CAN / CANFD
- [ ] JT808
- [ ] GB32960
- [ ] GB17691
- [ ] UDS
- [ ] OTA

电源：
- [ ] PMU / sleep / wakeup
- [ ] watchdog

存储：
- [ ] SRT（属性持久化）
- [ ] NVM（队列/分区）
- [ ] file system

安全：
- [ ] certificate / key
- [ ] secure boot
- [ ] eFuse

硬件：
- [ ] GNSS
- [ ] cellular / SIM
- [ ] sensor / ADC
```

## 5. 已知边界

```markdown
# Suspected Boundary

[勾选或描述涉及的高风险边界，AI 会据此加载对应的 spec/knowledge]

- [ ] MCU/MPU 合约（XCU 通道、共享内存）
- [ ] PMU 电源（sleep / wake / reboot / watchdog）
- [ ] 存储持久化（SRT / NVM）
- [ ] 安全流程（OTA / 证书 / key / secure boot）
- [ ] 协议栈（JT808 / GB32960 / GB17691 / UDS）
- [ ] 供应商（SDK / AUTOSAR / 生成配置 / 构建系统）
- [ ] 对端 ECU（EMS / TCU / ABS / BCM）
```

## 6. 复现环境（嵌入式特需）

```markdown
# Reproduction Environment

硬件环境：
- [ ] 台架
- [ ] 实车
- [ ] 单板
- ECU 硬件版本：[填写]
- 对端 ECU 型号及固件版本（CAN 问题必填）：[填写]

软件环境：
- 本端 MCU 固件版本：[填写]
- 本端 MPU 固件版本：[填写]
- 配置版本（SRT/NVM 是否刷写过）：[填写]
- 最近一次刷写方式：Keil / OTA / factory

复现条件：
- 冷启 / 热启 / wakeup / 其他：[填写]
- 必现 / 概率性：[填写]
- 概率：[填写]（如 "约 30%，wakeup 后 500ms 内"）
- 最小复现步骤：
  1. [步骤 1]
  2. [步骤 2]
  3. [观察结果]
```

## 7. 症状时间线

```markdown
# Symptom Timeline

[比分散描述更清晰。按时间或操作顺序列出关键节点]

T+0ms:    [第一个事件]
T+200ms:  [后续事件]
T+500ms:  [异常点] ← 问题在此处出现
T+1s:     [下游影响]

或按操作顺序：
Step 1: [操作] → [预期] → [实际]
Step 2: [操作] → [预期] → [实际]
```

## 8. 信号级细节（协议/通信问题时必填）

```markdown
# Signal-Level Detail

协议类型：CAN / UDS / 32960 / JT808

具体信号：
  - CAN ID: 0x[填写]
  - 信号名: [填写]
  - Byte offset: [填写]
  - Bit length: [填写]
  - 期望值: [填写]
  - 实际值: [填写]
  - 采样时间点: [填写（如 "wakeup 后 500ms"）]
  - 对端 ECU: [填写]

[如有多个异常信号，逐一列出]
```

## 9. 代码层边界

```markdown
# Code Boundary

涉及代码层级（可多选）：
- [ ] Application（自研，可自由修改）
- [ ] RTE / Middleware（自研框架，谨慎修改）
- [ ] BSP / Driver（供应商提供，禁止或受限修改）
- [ ] AUTOSAR Generated（工具生成，禁止修改）
- [ ] Vendor SDK（芯片/模组厂商，禁止修改）
- [ ] Third-party Library（开源/商业库）

涉及文件及层级：
  - path/to/file1.c  [自研]
  - path/to/vendor_driver.c  [供应商 - 只读]
```

## 10. 回归上下文

```markdown
# Regression Context

上次正常工作：
- 版本/commit：[填写]
- 时间：[填写]
- 触发变更（如果有怀疑）：[填写]

最近相关变更：
- commit [hash]: [简述]
- commit [hash]: [简述]
```

## 11. 期望验证方式

```markdown
# Expected Verification

- [ ] 现象消失
- [ ] 关联功能不受影响（列出）
- [ ] OTA 正常
- [ ] reboot 不受影响
- [ ] serial log 无新增异常
- [ ] CAN 报文符合预期
- [ ] 其他：[填写]
```

---

# Part C: Asset 输入

少写长文，多上传结构化资产。

## 12. 推荐资产

| 资产类型 | 优先级 | 格式 | 示例文件 |
|---------|--------|------|---------|
| 拓扑/架构图 | 最高 | draw.io / Excalidraw / Mermaid / PNG | `assets/topology.png` |
| 时序图 | 非常高 | 同上 | `assets/wakeup_sequence.png` |
| 状态机图 | 推荐 | 同上 | `assets/heartbeat_state.png` |
| 日志 | 推荐 | .log / .txt | `assets/serial.log` |
| 协议抓包 | CAN/网络问题必填 | .cap / .pcap | `assets/can.cap` |
| 电源时序图 | PMU 问题推荐 | PNG / PDF | `assets/power_timing.png` |

文件放在对应任务目录下：

```text
.trellis/tasks/<task-slug>/
  intake.md                 ← 本模板（人类填写部分）
  assets/
    topology.png
    wakeup_sequence.png
    serial.log
    can.cap
```

---

# Part D: AI 编译流程

人类输入 intake.md 后，AI 自动执行以下步骤，输出结构化上下文。

## Step 0: Asset Pre-parse

```yaml
# AI 自动执行
- 读取 topology 图 → 提取模块连接关系
- 读取 sequence 图 → 提取时序节点
- 扫描日志文件   → 标记异常时间线和关键字
- 解析 CAN cap   → 统计 CAN ID、周期、异常帧
- Mermaid 文本图 → 直接解析结构
- 非文本图（PNG） → 提醒用户补充文字描述或导出 SVG
```

## Step 1: Boundary Detection

```yaml
# AI 自动识别，附置信度
boundary:
  - type: MCU_MPU
    confidence: high
    source: "topology 图显示 MCU↔XCU↔MPU，用户明确提到 heartbeat MCU 侧"
  - type: SRT
    confidence: medium
    source: "用户提到 'SRT sync'，但未确认涉及 persistence 层"
```

## Step 2: Ownership Detection

```yaml
ownership:
  heartbeat: MCU
  persistence: MPU
  wakeup_state: MPU
```

## Step 3: Sequence Extraction

```yaml
sequence:
  - wakeup
  - MCU boot
  - XCU sync
  - MPU restore
  - SRT recover
  - heartbeat restore
```

## Step 4: Knowledge Routing

```yaml
# AI 根据 boundary + ownership 自动加载
knowledge:
  - spec/architecture-boundaries.md
  - spec/mcu-mpu-change-rules.md
  - knowledge/architecture/xcu-communication.md
  - knowledge/storage/srt-properties.md

skills:  # 匹配合适的 method skill
  - analyze-sync-failure
  - analyze-srt-recovery
```

## Step 5: Risk Detection

```yaml
risk:
  - type: cross_cpu_sync
    severity: high
    reason: "heartbeat 跨 MCU/MPU，同步失败导致云端离线"
  - type: persistence_recovery
    severity: medium
    reason: "wakeup 后 SRT 恢复时序不确定"
  - type: wakeup_timing
    severity: medium
    reason: "MPU ready 与 MCU heartbeat 之间存在竞态"
```

## Step 6: Verification Plan

```yaml
verify:
  - item: wakeup_smoke_test
    method: "冷启 → wakeup → 检查 heartbeat 在 MCU ready 后 1s 内恢复"
  - item: reboot_test
    method: "reboot 后验证正常流程不受影响"
  - item: serial_log_check
    method: "MCU 侧 serial log 无新增 ERROR"
  - item: can_trace_check
    method: "CAN trace 确认 heartbeat 报文周期和内容正确"
```

## Step 7: Ambiguity Flag

AI 推断不了时，生成待确认项：

```yaml
ambiguities:
  - question: "heartbeat 未恢复是因为 MCU 没发，还是 MPU 没收？"
    need: "MCU 侧 serial log 或 CAN trace"
    impact: "决定排查起点是 MCU 发送端还是 MPU 接收端"
  - question: "wakeup 类型是 RTC 唤醒还是 CAN 唤醒？"
    need: "确认 PMU 唤醒源"
    impact: "不同唤醒源对应不同的恢复时序"
```

---

# Part E: 输出对接

AI 编译完成的 `context.generated.yaml` 拆入 Trellis 任务管理：

```text
intake.md（人类输入）
    ↓ AI Requirement Compiler
context.generated.yaml
    ↓ 拆分
├── implement.jsonl   ← boundary + knowledge 路由 + skill 选择
├── check.jsonl       ← verification checklist
└── job-packet.md     ← 如果走双机执行，包含 required_context + commands
```

双机执行时，AI 生成的 `job-packet.md` 应优先使用当前 Windows canonical
workspace，而不是 Mac 本地路径：

```yaml
source_of_truth: windows
workspace: <windows-workspace>
observation:
  mac_smb_path: <optional-mac-observation-path>
  mode: read-mostly
execution:
  mode: native-agent
  command: <agent-command> --workspace <win-workspace> --execute --json
handoff:
  file: .trellis/tasks/<task>/handoff.md
  sessions: .trellis/tasks/<task>/remote-sessions.jsonl
```

## 与 Trellis 工作流对接

```
/trellis:start
    → 如果用户描述新需求，AI 自动打开本模板引导填写
    → trellis-brainstorm 将 intake.md 转化为 task + PRD
    → AI 编译 context.generated.yaml
    → 填入 implement.jsonl / check.jsonl
    → 后续走 Trellis 标准流程
```

---

# Part F: 人类职责

| 人类 | AI |
|------|-----|
| 描述问题和现象 | 提取边界和所属模块 |
| 上传 topology / 时序图 / 日志 / CAN cap | 解析并结构化 |
| 回答 AI 的 ambiguity 追问 | 生成追问 |
| 修正 AI 输出中的错误 | 标注置信度（human review low-confidence items）|
| 做最终治理决策 | 路由 knowledge 和 skill |

**人类不负责**：手写 YAML、手写依赖图、手写 runtime context。
**人类负责**：描述问题 + 上传资产 + 修正理解 + 最终治理。
