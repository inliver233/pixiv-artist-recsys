---
mode: plan
task: Pixiv Refresh Inspector
created_at: "2026-03-18T09:13:04+08:00"
complexity: medium
---

# Plan: Pixiv Refresh Inspector

## Goal
- 继续增强可运行性：围绕 Pixiv refresh token 打通更多“直接取数”能力，补齐 Pixiv 信息检查/调试链路，便于本地验证 token、用户、作品与关联接口。

## Scope
- In:
  - 生成第十二批 plan / issue 资产并更新路线图
  - 实现 Pixiv inspector service / payload serializer
  - 扩展本地 API 支持 Pixiv 信息查询端点
  - 扩展 CLI 支持基于 refresh token 的 Pixiv 直接查询命令
- Out:
  - Web UI
  - 多账号调度策略
  - 下载原图文件

## Assumptions / Dependencies
- 继续使用已有 OAuth refresh + Pixiv App API client。
- inspector 主要用于本地调试、验证 refresh token 有效性与接口返回结构。
- 输出优先 JSON。

## Phases
1. 生成第十二批 plan 与 issue CSV，并更新架构文档。
2. 实现 Pixiv inspector service。
3. 扩展 API 支持 following/user-detail/user-illusts/illust-detail/related 查询。
4. 扩展 CLI 直查命令并复用 facade。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-18_09-13-04-pixiv-refresh-inspector.csv`
- API/Application -> `python -m unittest -v tests.test_api.ApiRouterTests tests.test_application.ApplicationFacadeTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-18_09-13-04-pixiv-refresh-inspector.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地 fake client 单测

## Acceptance Checklist
- [ ] 已生成第十二批 plan 与 Issue CSV
- [ ] 已实现 Pixiv inspector service / facade payload
- [ ] 已实现 Pixiv 信息查询 API 端点
- [ ] 已实现 Pixiv 信息查询 CLI 命令
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- refresh token 相关命令需要尽量避免在日志中泄漏敏感值。
- Pixiv 接口字段存在变化风险，payload serializer 需尽量稳健。

## Rollback / Recovery
- 若 inspector 命令不稳定，可保留 service 层并暂时关闭 API/CLI 入口。

## Checkpoints
- Commit after: DOCS-012 / CORE-009 / API-003 / APP-011 / TEST-012

## References
- src/pixiv_artist_recsys/pixiv/client.py
- src/pixiv_artist_recsys/application/facade.py
- src/pixiv_artist_recsys/api/router.py
- src/pixiv_artist_recsys/cli.py
