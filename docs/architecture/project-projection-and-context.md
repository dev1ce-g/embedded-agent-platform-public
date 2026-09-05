# Project Projection And Context

本文定义项目如何在不依赖工作流引擎或模型专用 CLI 的情况下接入 Embedded Agent
Platform。

## 投影结构

```text
<project>/
  AGENTS.md
  .embedded-agent/
    manifest.json
    rules/
      platform/
      project/
    context/
    knowledge/
    evidence/       optional platform-local receipts/cache
```

| 内容 | 所有者 | 默认 Git 策略 |
| --- | --- | --- |
| `manifest.json` | Bootstrap | 本地生成、默认 exclude |
| `rules/platform/` | Rule Pack Installer | 平台管理、默认 exclude |
| `context/` | Discovery / Bootstrap | 可重复生成的事实与知识索引，默认 exclude |
| `rules/project/` | 项目 | 不自动 exclude，可纳入项目 Git |
| `knowledge/` | 项目 | 不自动 exclude，可纳入项目 Git 或引用已有文档 |
| `evidence/` | Runtime / Adapter | 可选的本地证据缓存，默认 exclude；权威结果仍由 Runtime 返回 |
| `AGENTS.md` managed block | Bootstrap | 保留项目已有内容，不自动提交 |

平台只安装短入口和可检索文档，不创建 task、workflow、hook 或模型配置。

## 一条命令接入

```bash
embedded-project init <project-path> --discovery local --json
```

初始化按以下顺序执行：

1. 校验目标、已有 managed marker 和参数。
2. 幂等安装 `embedded-engineering-v1` 到 `rules/platform/`。
3. 合并项目 `AGENTS.md` 的平台 managed block。
4. 只把平台管理/生成路径加入该 worktree 的 `.git/info/exclude`。
5. 执行 parser-first Discovery，生成 `context/`。
6. 按显式配置登记 Windows workspace，并可选构建 Runtime Knowledge。

Bootstrap 不执行构建、CI、烧写、复位、CAN/ADB 操作或凭据读取。

## 刷新与检查

```bash
embedded-project doctor <project-path> --json
embedded-project refresh <project-path> --discovery local --json
```

`doctor` 只验证投影完整性、Rule Pack、managed block 和旧目录提示。`refresh` 只更新生成
上下文及显式请求的 Runtime Background/Knowledge，不改项目规则或知识。

规则升级再次运行 `init`。内容相同则跳过；项目若修改平台管理文件，更新内容写入确定性的
候选文件，禁止静默覆盖。

## 外部规则与知识

平台 Rule Pack 是通用工程约束，不包含产品事实。项目可以：

- 在 `.embedded-agent/rules/project/` 保存项目级规则；
- 在 `.embedded-agent/knowledge/` 保存经确认的长期知识；
- 直接从 `AGENTS.md` 指向仓库已有 docs、接口文档或独立知识库；
- 由索引器记录 path、title、content hash 和 size；scope、version、freshness 与
  validation metadata 留给后续检索层扩展。

自动生成的索引位于 `.embedded-agent/context/knowledge-index.json`；它不会占用或覆盖
项目自有的 `knowledge/` 文件名。

自动检索只决定给模型提供哪些资料，不自动把低置信度结论提升为规范。

## 多主机项目

只有需要 Windows Runtime 时才登记：

```bash
embedded-project init <project-path> \
  --project-id <project-id> \
  --windows-workspace '<windows-workspace>' \
  --build-knowledge \
  --json
```

`context/workspace-manifest.json` 记录源码工作区、远端、分支和 exact Commit。跨工作区同步
使用 Git 和精确 SHA；Bootstrap 不复制产品源码，也不覆盖脏工作区。

## Trellis 迁移

旧投影只通过显式命令读取：

```bash
embedded-project migrate-trellis <project-path> --dry-run --json
embedded-project migrate-trellis <project-path> --json
```

迁移是单向、非破坏的。它不会调用 Trellis、删除旧目录，或把旧 workflow/tasks/hooks 恢复
成活动状态。新 `.embedded-agent/` 始终是唯一活动来源。详细映射见
[迁移指南](../migration/from-trellis.md)。

## 失败规则

遇到下列情况必须停止并报告：

- managed marker 缺失、倒序或重复；
- Rule Pack 来源缺失或冲突候选不可安全写入；
- project ID 与 Windows workspace 不完整或指向另一项目；
- 工作区无法证明 Git 根或 exact Commit；
- 迁移候选文件也已存在且内容不同，无法安全保留冲突版本；
- 操作需要 Bootstrap 明确禁止的 Runtime 能力。
