# Embedded Agent Platform 开发规则

本仓库维护 Embedded Platform Core、Trellis Spec、项目接入脚本和主机能力 Adapter。任意
具备所需能力的 Agent 都可以拥有完整项目；主机不预设规划或执行角色。修改仓库时，先
识别所属层，再读取对应文档和测试；不要把产品项目事实写入平台模板。

## 入口

- 改 bootstrap、模板安装或项目投影：读取 `docs/architecture/embedded-bootstrap-and-marketplace.md`、`bootstrap/tests/test_embedded_bootstrap.py`。
- 改任务所有权、主机路由或平台边界：读取 `docs/architecture/platform-capability-model.md`、`marketplace/specs/embedded-dual-machine-v1/platform-operating-model.md` 和 `agent-governance.md`。
- 改跨主机同步或 Windows 拓扑：读取 `docs/architecture/dual-machine-agent-system.md`。
- 改 Windows 命令、Jenkins、构建、日志或设备操作：读取 `marketplace/specs/embedded-dual-machine-v1/embedded-runtime-workflow.md` 及命中领域的 Spec；Runtime 的固定命令面、Gate 和结构化证据属于公共 contract。
- 改项目级 Agent 行为：保持根 `AGENTS.md` 为短入口，详细规则放入 `.trellis/spec/`，并通过 bootstrap 测试验证首次安装、重复安装和冲突保留。

## 分层边界

- `marketplace/` 只发布可复用 Spec，不包含机器凭据、项目事实、任务状态或运行产物。
- `skills/` 发布与平台 Runtime 配套的 Agent Skill；Skill 只负责意图路由、固定命令选择、Gate 和证据解释，不复制 Runtime 实现。
- `bootstrap/` 负责幂等接入、项目级 `AGENTS.md` 补充块、Spec 安装、Discovery 和 Workspace Manifest；不得执行构建、Jenkins、烧写或设备操作。
- `runtime/mac/` 是兼容传输 Adapter，只负责受控传输和参数转发。
- `runtime/wsl/` 是 Windows 互操作 Adapter，只把参数数组交给固定的 Windows Python 入口，不实现第二套业务逻辑。
- `runtime/windows/` 是 Windows 能力 Adapter，负责固定命令面、路径约束、操作 Gate、日志和证据；不得增加任意 shell 传递。
- `docs/architecture/` 解释稳定架构与所有权；命令级强制规则以代码、测试和 `marketplace/specs/` 为准。

## 变更规则

- 修改前执行 `git status --short --branch` 和目标文件 diff，保护并存的用户改动。本仓库经常同时开发 Runtime 功能，避免无关格式化和整文件重写。
- 新增 Runtime 命令或输出字段时，同时更新所有受影响的主机 Adapter、README/Spec 和测试；JSON schema、错误码、Gate 或路径边界按公共 Interface 处理。
- 新增项目级规则时优先写正向完成条件和精确指针。避免在全局 `~/.codex/AGENTS.md` 重复嵌入式细节。
- 新增或修改平台 Skill 时，同步更新 `skills/index.json`，运行 Skill 校验，并保持 Runtime contract 为命令面唯一来源。
- 修改安装行为必须保持幂等：首次创建、内容相同跳过、项目已有内容保留、平台更新以 managed block 或候选文件呈现。
- 任何会构建、触发 CI、推送、发布、签名、烧写、复位或操作设备的测试都不是默认测试；需要用户明确授权和对应 Gate。

## 验证

- Bootstrap、Spec 或项目投影：`PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache python3 -m unittest discover -s bootstrap/tests -v`。
- Windows Runtime Python：运行 `runtime/windows/embedded-agent/tests/` 中与改动直接相关的测试；跨平台逻辑至少运行该目录全量测试。
- Mac wrapper：运行 `bootstrap/tests/test_mac_embedded_agent_wrapper.py` 及 `bash -n runtime/mac/bin/embedded-agent`。
- 文档和模板：运行 `git diff --check`，并在临时 Git 仓库验证生成文件、重复运行和 `git info/exclude`。

交付时区分本机测试、Windows 构建、Jenkins 和硬件验证；只声明实际取得证据的层级。
