# CodexHost 项目评估

> 本文是特定版本和时间点的研究记录。关于 Agent 所有权与主机职责的结论，统一以
> [平台能力模型](../architecture/platform-capability-model.md)为准。Mac、WSL 和 Windows
> 不再预设固定角色。

> 研究对象：[`BytePioneer-AI/codex-host`](https://github.com/BytePioneer-AI/codex-host)
>
> 证据快照：`main@51037e53bc8cf73143755efc65e25a895b627aa7`，2026-08-31
>
> 范围：只使用项目 README、源码、GitHub Actions、Release 与仓库元数据等第一方来源。本文区分“项目已实现/自述”和“对 embedded-agent-platform 的推断与建议”。

## 结论

CodexHost 适合作为 **Codex Desktop 的多 Harness 展示与协议路由层**，不适合替代 embedded-agent-platform 的 Windows Native Runtime、固定 CLI/JSON contract、操作 Gate 和证据链。推荐的组合方式是：

```text
Mac
  Codex Desktop + CodexHost（UI、会话入口、SSH 客户端）
                        │ 官方 SSH Workspace
                        ▼
Windows WSL2
  CodexHost Remote Host（可选）
  Codex / Claude Code / Pi 等 Harness
  Engineering Rules / AGENTS.md / Skills / Git 工作区
                        │ 固定 CLI；以后可加受限 MCP adapter
                        ▼
Windows Native
  embedded-agent Runtime
  Gate / Job / JSON evidence / Keil / J-Link / ADB / Jenkins
```

它与本平台是互补关系：CodexHost 决定“哪个 Harness 处理会话以及如何投影到 Codex Desktop”，embedded-agent 决定“哪些 Windows/硬件操作允许执行、如何验证、证据保存在哪里”。短期应先做隔离试点并锁定版本，不应直接跟随 `main`：项目创建仅一个多月、发布频繁，且本次快照的主干 CI 为红色。

## 1. 它解决什么问题

CodexHost 在官方 Codex Desktop 中加入 Agent/Model 选择、外部 Harness 会话和跨 Harness 委派。项目自述的核心实现不是重做聊天客户端，而是：

- 通过 CDP/Electron Inspector 增强官方 Desktop 的 Renderer；
- 用原生 Shim 代理 Codex CLI/app-server；
- 分别通过 Harness 的原生接口接入 Pi、Claude Code、DeepSeek Harness、Grok 和 OMP；
- 把外部 Harness 的流式文本、工具、Diff、审批、提问和历史投影到 Codex Desktop。

这些定位可见固定快照的 [README](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/README.md)；实际 adapter 注册集中在 [`adapter-composition.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/host-runtime/src/adapter-composition.ts#L1-L74)。Launcher 为 Inspector 和控制端分配 loopback 端口与随机 nonce，并启动 Desktop Controller 注入 Renderer，见 [`desktop_attachment.rs`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/crates/launcher/src/desktop_attachment.rs#L24-L44)、[`main.rs`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/crates/launcher/src/main.rs#L413-L430) 和 [`production-controller.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/desktop-control/src/production-controller.ts#L90-L103)。

这意味着它对官方 Desktop 的内部 Renderer/app-server contract 有较强耦合。源码为 Renderer 维护版本化 adapter 和兼容检查，但官方 Desktop 更新仍可能造成短期失配；这是此类运行时增强方案的固有升级风险，不应与嵌入式执行链的可用性绑定。

## 2. 安装与运行链路

项目提供两种普通安装方式：全局安装 `@codexhost/cli` 后运行 `codexhost`，或下载 macOS/Windows 安装包。开发环境要求 Node.js 22.19+ 或 24、Rust 和官方 Codex Desktop；Linux 通过 npm 安装并要求官方 ChatGPT `.deb`/`.rpm`、glibc 2.35+、`/proc` 和 `pidfd`。依据为 [README](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/README.md)、[`docs/linux.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/linux.md) 和 [`package.json`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/package.json)。

运行时链路可以概括为：

1. Launcher 发现并校验官方 Desktop 安装和已打包的 Codex CLI；
2. 启动打包的 Node、Host Runtime、Desktop Controller、Renderer bundle 和原生 Shim；
3. Shim 对普通命令保持字节透明转发，对 app-server 场景启动 Host Runtime；
4. `AppServerHost` 将官方 Codex 请求继续交给 stock app-server，将带外部 Harness 标识的 Thread 路由到对应 adapter；
5. Renderer 把 Harness、Model、Permission Mode 等选择编码进已有 Desktop 请求，并展示投影后的事件。

打包资源和启动参数可从 [`main.rs`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/crates/launcher/src/main.rs#L372-L430) 核对；Host Runtime 的创建和远程分支位于 [`run-host-runtime.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/host-runtime/src/run-host-runtime.ts#L135-L280)。

## 3. SSH、WSL、Windows 与 Remote Control

### SSH Remote

SSH Remote 是当前更适合本平台目标架构的链路。远端安装：

```bash
npm install -g @codexhost/cli
codexhost remote install
codexhost remote start
codexhost remote status
```

项目要求两端 CodexHost 版本一致；远端 Harness 在远端安装和登录，凭据不复制到客户端。Remote Host 使用私有 Unix socket，共享一个长期 stock app-server listener，每个 Desktop 连接保留独立 Host session，而 Thread、订阅和 writer/observer 协调仍由 stock app-server 持有。[`docs/remote-ssh-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-ssh-host.md#L7-L15) [`docs/remote-ssh-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-ssh-host.md#L33-L50)

远端 Host 明确支持 macOS 和 x64/ARM64 Linux，不支持 Windows 作为 SSH Host，因为这条 transport 依赖 Unix socket；Windows 可以作为客户端。[`docs/remote-ssh-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-ssh-host.md#L9-L15)

### WSL 判断

项目文档没有把 WSL 列为单独验证平台。WSL2 在接口形态上属于 Linux、具备 Unix socket，因此“Mac Codex Desktop → 官方 SSH → WSL2 CodexHost Remote Host”在架构上吻合；但这属于推断，不是项目已声明的支持组合。试点前必须验证：

- WSL 发行版满足 Node、glibc、`/proc`、`pidfd` 等要求；
- 官方 Codex CLI 和 Codex Desktop SSH bootstrap 在登录/非交互 shell 中都能找到 CodexHost Shim；
- Windows interop 调用 `embedded-agent.ps1` 的 PATH、编码、退出码和 JSON 不受 Shim/代理环境影响；
- 双客户端或重连时 Thread writer/observer 语义符合预期。

### Windows Remote Control

Windows 作为被控 Host 时，项目提供实验性的 Remote Control 方案：保留官方配对、账号认证和 relay，不新增公网服务或 TCP listener；控制端当前验证组合是 macOS。它通过官方 `process/*` 方法启动固定 bridge，再连接 Windows 当前用户的随机 named pipe，不接受来自请求的任意路径或命令。[`docs/remote-control-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-control-host.md#L1-L12) [`docs/remote-control-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-control-host.md#L22-L32)

这条路适合对比验证，不建议现在作为 embedded-agent-platform 主链路：它仍是实验功能，而且“Windows Desktop 环境”并不等价于当前已建立的 WSL Git/Agent 工作区。现阶段官方 SSH 到 WSL 更贴合“Mac 只做运行壳”的目标。

## 4. MCP 支持判断

根 `package.json` 声明了 `@modelcontextprotocol/sdk`，但固定快照的用户文档与主运行链路没有发布可供 embedded-agent 直接接入的 MCP Server、tool schema 或授权 contract。现有可见控制面主要是：

- Codex app-server JSON-RPC；
- Harness 原生 adapter；
- 本地跨 Harness 委派 CLI；
- 仅监听 `127.0.0.1`、使用随机 Bearer token 的内部 HTTP delegation server。

内部服务限制 2 MiB 请求体，并只发布固定 `/v1/harness/*`、`/v1/delegate/*`、`/v1/thread/*` 端点，见 [`delegation-control-server.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/host-runtime/src/delegation-control-server.ts#L16-L125)；CLI 明确不会返回工具调用、工具输出、文件活动、隐藏 reasoning 或私有 transcript，见 [`delegation-cli.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/host-runtime/src/delegation-cli.ts#L71-L101)。

因此，**采用 CodexHost 不是把 embedded-agent 改成 MCP 的理由**。建议顺序是：

1. 先在 WSL 提供与现有 contract 完全一致的 `embedded-agent` CLI wrapper；
2. 让 CodexHost 下的各 Harness 通过同一套项目 skill/AGENTS 规则调用该 CLI；
3. 只有当类型化工具发现、参数校验和审批体验确有收益时，再增加 WSL 本地 STDIO MCP adapter；
4. MCP adapter 只能调用 Runtime Core 的固定操作，不得暴露任意 shell，也不得复制 Gate 逻辑。

## 5. 安全、权限与状态

### 已实现的保护

- Inspector、Controller attachment 和 delegation server 均绑定 loopback；Controller 参数要求明确端口与随机 nonce。[`desktop_attachment.rs`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/crates/launcher/src/desktop_attachment.rs#L24-L44) [`production-controller.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/desktop-control/src/production-controller.ts#L90-L103)
- Remote SSH 将凭据留在远端，卸载时验证入口摘要，只删除 managed entry/profile block，并保留 Mapping Store 数据用于恢复。[`docs/remote-ssh-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-ssh-host.md#L60-L73)
- Remote Control 使用官方 relay、固定 bridge 和当前用户 named pipe，descriptor 不含凭据，并校验 owner PID 存活。[`docs/remote-control-host.md`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/docs/remote-control-host.md#L22-L32)
- Linux 本地状态目录/文件执行 owner、`0700`/`0600` 与 `O_NOFOLLOW` 检查，降低符号链接和路径替换风险。[`secure_storage.rs`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/crates/launcher/src/secure_storage.rs#L55-L114) [`secure_storage.rs`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/crates/launcher/src/secure_storage.rs#L150-L213)

### 不能替代本平台 Gate 的原因

CodexHost 投影各 Harness 自身的权限模式。以 Claude Code 为例，它同时暴露 `plan`、`default`、`acceptEdits`、`auto` 和被明确标记为危险的 `bypassPermissions`。[`permission-modes.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/adapters/claude-code/src/permission-modes.ts#L10-L60)

这些是会话工具权限，不知道烧写、复位、eFuse、签名、设备占用、构建证据等嵌入式语义。因此：

- CodexHost UI 审批不能替代 embedded-agent 的高风险确认；
- 即使 Harness 选择 bypass/auto，Runtime 仍必须 fail closed；
- Windows 凭据、设备句柄和完整日志继续留在 Windows Runtime；
- 不应让 CodexHost adapter 直接获得任意 PowerShell、ADB shell、J-Link 或 Keil 命令面。

### 状态与会话所有权

CodexHost 的 Mapping Store 默认位于 `$CODEXHOST_DATA_DIR/mapping-store` 或 `~/.codexhost/mapping-store`，保存 Host Thread ↔ Native Session/Turn、fork、subagent 和 delegation 映射。[`external-thread-repository.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/host-runtime/src/external-thread-repository.ts#L29-L95) 记录使用严格 schema，并校验 Thread、Harness、Native Session 和 Turn 的归属一致性。[`records.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/mapping-store/src/records.ts#L26-L130)

它不是完整 transcript 的唯一真相：例如 Claude adapter 会从 Harness 自身的 `~/.claude/projects/.../*.jsonl` 恢复历史。[`claude-transcript.ts`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/packages/adapters/claude-code/src/claude-transcript.ts#L23-L86) 因而本平台仍应保持分层状态：

- CodexHost：展示会话与跨 Harness 映射；
- Active Context：目标、授权、决策和 handoff；
- embedded-agent：Job、日志、artifact、Gate 和设备证据；
- Harness：自身 Native Session/transcript。

不要把 CodexHost Mapping Store 当作构建、烧写或硬件验证证据。

## 6. 工程与发布成熟度

正向证据：

- TypeScript + Rust workspace，边界检查、类型检查、Vitest、Cargo fmt/clippy/test、Playwright E2E 和多套 live/hermetic Gate 都有脚本入口；
- CI 覆盖 Ubuntu x64、Linux ARM64、macOS 14 和 Windows，并执行统一 `npm run check`；
- Release workflow 覆盖 macOS/Windows/Linux 的 x64/ARM64，校验 annotated semver tag、版本一致性、非空产物，并使用 npm provenance。

证据见 [`package.json`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/package.json)、[`.github/workflows/ci.yml`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/.github/workflows/ci.yml) 和 [`.github/workflows/release-packages.yml`](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/.github/workflows/release-packages.yml)。固定快照树按 `*.test.ts`、`*.test.mjs` 和 Rust `tests/` 源文件统计为 177 个测试文件。这只是规模线索，不代表全部行为均被覆盖。

风险证据：

- 仓库创建于 2026-07-24，仍处于高频演进期；截至快照约 603 次提交、25 个 Release；
- 最新稳定版为 [`v0.4.0`](https://github.com/BytePioneer-AI/codex-host/releases/tag/v0.4.0)，tag 对应提交 `dea7498527b47eac4e12e977569588230d065a97`；
- 本次快照 `main` 的四个平台 CI 均在 Prettier 检查失败，后续 lint/typecheck/test 未执行，见 [Actions run 33362981506](https://github.com/BytePioneer-AI/codex-host/actions/runs/33362981506)；
- 主分支当前未保护；CI 中仍有 `dtolnay/rust-toolchain@master` 等可变 action 引用。

综合判断：测试资产和发布自动化的“覆盖设计”较强，但项目年龄、主干红灯和发布速度说明“稳定执行纪律”仍未达到关键基础设施依赖的标准。试点应锁定 release/commit、自行复跑，并保留 stock Codex 回退入口。

## 7. 许可证与供应链

项目代码采用 [MIT License](https://github.com/BytePioneer-AI/codex-host/blob/51037e53bc8cf73143755efc65e25a895b627aa7/LICENSE)，允许使用、修改和再分发，但仍需保留版权与许可声明。MIT 只覆盖该仓库代码，不改变官方 Codex Desktop、Claude Code、Pi 等第三方产品和账号条款。

`v0.4.0` GitHub Release 为四个 macOS/Windows 安装包发布了 GitHub asset SHA-256 digest；安装时应核对 digest。README 对 macOS 验证问题建议移除 quarantine，这会弱化操作系统下载保护，企业环境不应把它作为默认路径；优先使用已验证来源、固定 digest 和隔离试装。

## 8. 与 embedded-agent-platform 的推荐结合方式

### P0：保持边界，完成 WSL 本地化

1. 在 WSL Linux home 中克隆 embedded-agent-platform 和产品项目；
2. 投影 `.embedded-agent` Context、AGENTS.md、Skills 与项目 task contract；
3. 使用 WSL `embedded-agent` wrapper，通过 Windows interop 调固定 Python 入口；
4. 保持 CLI 参数、JSON、退出码、Gate、日志和证据 contract 不变；
5. Mac wrapper 保留为恢复/诊断入口。

这一阶段不依赖 CodexHost，先证明核心 Windows 执行链稳定。

### P1：隔离试点 CodexHost SSH Remote

1. 锁定 `v0.4.0` 或经验证的精确 SHA，不跟随 `main`；
2. 在 Mac 与 WSL 安装相同版本；
3. 只选择一个非硬件项目验证 Codex、Claude Code/Pi 的 Thread 创建、恢复、重连、Diff、审批和 cwd；
4. 再验证一个只读 embedded-agent 命令，如 `status`、`project show`、`tool read`；
5. 最后验证构建，不在试点中直接开放 flash/reset/eFuse。

验收必须包含 stock Codex 回退、Codex Desktop 升级后的兼容检查、同一项目的一写者规则，以及 CodexHost/WSL/Windows 三层日志的关联 ID。

### P2：按收益决定是否增加 MCP

若多个 Harness 都需要稳定发现 embedded-agent 工具，可以在 WSL 增加本地 STDIO MCP adapter，但 Runtime Core 仍是唯一操作真相：

```text
Codex / Claude / Pi
       │ CLI skill 或 STDIO MCP
       ▼
WSL embedded-agent adapter
       │ 固定 JSON contract
       ▼
Windows embedded-agent Runtime + Gate
```

优先开放 `project show/check-stale`、`git status/diff`、`tool read/rg/tail`、`build`、`job status/output` 等固定能力；设备写入、烧写、复位、签名和凭据操作继续要求 Harness 审批与 Runtime Gate 双重确认。任何 MCP 工具都不得把任意命令字符串传给 Windows。

## 9. 最终建议

| 决策项 | 建议 |
| --- | --- |
| 是否用 CodexHost 替换 embedded-agent | 否；两者职责不同 |
| 是否值得试点 | 是；对多 Harness、统一 UI 和远端会话价值明显 |
| 远程方式 | 按任务能力选择 Remote Host，不固定源主机 |
| Windows Remote Control | 仅做实验对比，不作为当前主链路 |
| 是否立即 MCP 化 | 否；先完成 WSL CLI adapter，再按收益增加受限 MCP |
| 版本策略 | 锁定 release/精确 SHA，自行复跑，不跟随 `main` |
| 权限策略 | CodexHost 权限仅作第一层；embedded-agent Gate 保持最终裁决 |
| 状态策略 | CodexHost 会话、Active Context、Runtime evidence 分开保存 |

总体上，CodexHost 可以作为可插拔的 UI/Harness Adapter，但不能替代 Embedded Platform
Core 或 Windows Native Runtime。试点应按任务能力选择主机：Windows/WSL 任务既可以
调用本地 Runtime，也可以拥有需求、架构、实现和验证的完整生命周期。
