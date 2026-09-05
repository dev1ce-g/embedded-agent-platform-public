# Embedded Agent Platform 开发规则

本仓库维护模型无关的 Embedded Context Plane、Engineering Rule Pack、Capability
Contract 和主机能力 Adapter。模型或 Agent 负责推理与任务编排；平台只负责提供可追溯
上下文、受控工具、风险门禁和结构化证据。

## 入口

- 改项目初始化、规则投影或迁移：读取
  `docs/architecture/project-projection-and-context.md` 和 bootstrap 测试。
- 改任务所有权、主机路由或平台边界：读取
  `docs/architecture/platform-capability-model.md`、
  `rules/embedded-engineering-v1/platform-operating-model.md` 和
  `rules/embedded-engineering-v1/agent-governance.md`。
- 改公共 JSON、Gate、Job 或证据字段：读取 `contracts/README.md`。公共字段必须保持
  向后兼容，或明确提升 contract major version。
- 改 Windows 命令、Jenkins、构建、日志或设备操作：读取
  `rules/embedded-engineering-v1/windows-runtime-capabilities.md` 及命中领域的 Rule。
- 改项目级 Agent 行为：保持项目根 `AGENTS.md` 为短入口，详细规则放入
  `.embedded-agent/rules/project/` 或可复用 Rule Pack。

## 分层边界

- `rules/` 发布可复用工程规则，不包含机器凭据、项目事实、任务状态或运行产物。
- `contracts/` 定义模型、客户端和 Adapter 之间的稳定数据契约。
- `skills/` 只负责意图路由、固定命令选择、Gate 和证据解释，不复制 Runtime 实现。
- `bootstrap/` 负责幂等接入、`AGENTS.md` managed block、Rule Pack、Discovery、迁移和
  Workspace Manifest；不得执行构建、CI、烧写或设备操作。
- `runtime/mac/` 和 `runtime/wsl/` 是传输 Adapter，不实现第二套业务逻辑。
- `runtime/windows/` 负责固定命令、路径约束、操作 Gate、持久 Job、日志和证据；不得
  增加任意 shell 传递，也不得启动或绑定某个特定模型。
- `.embedded-agent/context/` 是生成事实；`.embedded-agent/rules/project/` 与
  `.embedded-agent/knowledge/` 是项目所有内容，Bootstrap 不得覆盖或整体忽略。

## 变更规则

- 修改前检查 Git 状态和目标文件差异，保护并存的用户改动；避免无关格式化。
- 新增 Runtime 命令或输出字段时，同步更新 Adapter、文档、Contract 和测试。
- 新增规则时优先写完成条件、风险边界和精确来源，不规定模型内部思维链。
- 安装与迁移必须幂等、非破坏：相同内容跳过，冲突生成候选或失败，禁止静默覆盖项目
  规则与知识。
- 旧 `.trellis/` 只有显式迁移命令可以读取内容；其他路径只允许检测其存在或将其排除在
  扫描之外。迁移不得调用 Trellis、删除旧目录或恢复旧 workflow/tasks 为活动平台状态。
- 任何构建、CI、推送、发布、签名、烧写、复位或设备操作都不是默认测试。

## 验证

- Bootstrap、Rule 或项目投影：
  `PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache python3 -m unittest discover -s bootstrap/tests -v`
- Windows Runtime：在 `runtime/windows/embedded-agent/` 运行
  `PYTHONPYCACHEPREFIX=/tmp/embedded-agent-platform-pycache python3 -m unittest discover -s tests -v`
- Shell Adapter：`bash -n install.sh runtime/mac/bin/embedded-agent runtime/wsl/bin/embedded-agent`
- 文档与模板：运行 `git diff --check`，并在临时 Git 仓库验证首次安装、重复安装、冲突和
  无 Trellis 环境。

交付时区分本机测试、Windows 构建、CI 和硬件验证，只声明实际取得证据的层级。
