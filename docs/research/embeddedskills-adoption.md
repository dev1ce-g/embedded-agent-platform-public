# embeddedskills 采纳评估

## 结论

可以借鉴 `zhinkgit/embeddedskills`，但不适合直接安装其完整工具包。上游 Skill 把自带 Python
脚本作为执行面；Embedded Agent Platform 要求 Windows 构建、调试和硬件操作通过固定的
`embedded-agent` Runtime Interface 获取 Gate 和结构化证据。

本次评估基于上游提交 `50d85f2766722ee7d43caa9633c2e9cc8ba6e429`。上游采用 MIT
License。本仓库只借鉴设计概念，没有复制上游脚本。

## 采纳状态

| 上游工具 | 处理方式 | 平台状态 | 原因 |
|---|---|---|---|
| Keil | 已重写 | 已有 `embedded-keil-build` | 保留工程和 Target 显式选择、结构化产物；构建改走 Runtime 和 Build Receipt。 |
| J-Link | 已重写 | 已有 `embedded-jlink-debug` | 保留 device、probe、RTT 和 GDB 分层；烧写绑定 Build Receipt 和设备 Gate。 |
| CAN | 本次新增 | `skills/embedded-can-runtime` | Runtime 已提供 ControlCAN、ZCANPro、有限时监控、发送和 UDS 固定命令。 |
| Workflow | 合并概念 | Trellis Workflow 和 Runtime Spec 已覆盖 | 使用项目 Context、Background 和 Receipt，不增加第二套 `.embeddedskills/state.json`。 |
| GCC/CMake | 候选 | Runtime 只有项目化 MPU 构建入口 | 增加通用 Skill 前，需要定义 CMake 工程发现、preset 选择和 Build Receipt contract。 |
| Serial | 暂缓 | 当前只支持 ADB TTY 元数据检查 | 串口负载读取会消费数据。先增加端口所有权、有限时采集和发送 Gate 的 Runtime 命令。 |
| OpenOCD | 暂缓 | 无受控 Runtime Adapter | 上游包含擦除、复位、写内存和 raw 命令，不能绕过平台设备 Gate。 |
| probe-rs | 暂缓 | 无受控 Runtime Adapter | 需要明确 chip、probe、固件 Receipt 和目标状态证据。 |
| EIDE | 暂缓 | 无 EIDE Runtime Adapter | 先确认实际项目需求和可重复的构建 contract。 |
| SSH、Terminal、Net | 不作为嵌入式工具 Skill 引入 | Runtime 已提供固定代理命令 | 任意命令传递会扩大机器执行面，与平台边界冲突。 |

## 可复用设计

- 多工程、多 Target、多探针和多适配器时返回候选项，不猜测。
- CLI 显式参数优先于历史状态。
- 构建、烧写、调试和观测分层。
- 命令返回结构化结果；流式数据使用有限范围或偏移量。
- 构建产物可以交给后续烧写或调试步骤，但必须保留来源证据。

## 不采纳的设计

- Skill 自带脚本直接调用 UV4、J-Link、厂商 DLL 或硬件端口。
- 自动把唯一扫描结果写入工程配置。
- 使用历史 `state.json` 作为烧写授权或当前项目事实。
- 以通用 `operation_mode` 代替项目 Gate。
- 暴露任意 shell、OpenOCD raw 命令、擦除或任意内存写入。

## 后续顺序

1. 将现有 `embedded-keil-build` 和 `embedded-jlink-debug` 的来源包纳入本仓库，统一版本和安装入口。
2. 为通用 CMake 构建定义工程发现、preset 选择、日志和产物 Receipt，再产出 `embedded-cmake-build`。
3. 为串口采集增加 Runtime Interface。明确端口所有权、有限时读取、日志证据和发送 Gate 后，再产出串口 Skill。
4. 只有项目实际采用 OpenOCD、probe-rs 或 EIDE 时，先实现对应 Runtime Adapter，再增加 Skill。

## 上游资料

- https://github.com/zhinkgit/embeddedskills
- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/keil/SKILL.md
- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/jlink/SKILL.md
- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/can/SKILL.md
- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/gcc/SKILL.md
- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/serial/SKILL.md
- https://github.com/zhinkgit/embeddedskills/blob/50d85f2766722ee7d43caa9633c2e9cc8ba6e429/workflow/SKILL.md
