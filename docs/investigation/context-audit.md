# Context Audit

## Scope
本项目启动前已审计以下上下文资产：

1. 工作区 `.codex/`
   - `prompts/plan.md`
   - `prompts/issues_csv_execute.md`
   - `skills/plan/*`
   - `skills/testing/*`
2. 工作区根目录工作流文件
   - `AGENTS.md`
   - `issues/README.md`
   - `docs/testing-policy.md`
   - `docs/mcp-tools.md`
3. Pixiv 相关参考仓库
   - `Pixiv-XP-Pusher`
   - `Random-image-api`
   - `pixiv-downloader`
   - `pixiv-viewer`
   - `x-algorithm`
4. 既有综合调查报告
   - `../基于pixiv的推荐系统pid获取详细调查报告.md`

## Direct impact on new repo
- 计划/Issue CSV 命名规则沿用 `.codex/skills/plan`。
- 执行约束沿用 AGENTS，但改为 **仅本地 Git**。
- 测试默认策略沿用 `docs/testing-policy.md`。
- 代码架构采用“调查 -> 计划 -> issue -> 骨架 -> 真实实现”的分层推进方式。

## Initial decisions
- 首版不用远端仓库，也不 push。
- 首版存储使用本地 SQLite。
- 首版先搭端口与骨架，再逐步接入 Pixiv 真正实现。
- 首版结果形态优先 CLI dry-run，而不是直接上 Web 服务。
