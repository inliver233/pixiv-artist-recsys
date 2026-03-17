---
mode: plan
task: Pixiv API Config Runtime
created_at: "2026-03-17T20:05:10+08:00"
complexity: complex
---

# Plan: Pixiv API Config Runtime

## Goal
- 在现有 CLI / runtime 基础上进一步增强架构：补齐强类型配置、增加本地 JSON API 路由与服务入口，便于后续服务化扩展。

## Scope
- In:
  - 生成第九批 plan / issue 资产并更新路线图
  - 扩展配置模型与 env 解析能力
  - 实现本地 JSON API router / server
  - CLI 增加 serve-api，并让默认值更多来自 settings
- Out:
  - 外部 Web 框架依赖
  - 认证授权层
  - 部署脚本 / 进程守护

## Assumptions / Dependencies
- 继续使用标准库实现本地 HTTP 服务。
- API 先服务于本地集成与调试，不暴露公网安全策略。
- runtime 继续作为装配层核心。

## Phases
1. 生成第九批 plan 与 issue CSV，并更新架构文档。
2. 扩展配置模型与 env 解析。
3. 实现 API router / server。
4. 扩展 CLI serve-api 与 settings default 集成。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_20-05-10-pixiv-api-config-runtime.csv`
- Config/runtime -> `python -m unittest -v tests.test_runtime.RuntimeTests`
- API -> `python -m unittest -v tests.test_api.ApiRouterTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_20-05-10-pixiv-api-config-runtime.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地标准库实现与单测

## Acceptance Checklist
- [ ] 已生成第九批 plan 与 Issue CSV
- [ ] 已实现强类型配置与 env helpers
- [ ] 已实现本地 JSON API router/server
- [ ] 已实现 CLI serve-api 与 settings 默认值接入
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 本地 JSON API 仍无认证，后续若开放网络需补安全控制。
- CLI parser 的动态默认值需注意测试环境变量影响。

## Rollback / Recovery
- 若 API server 层不稳定，可保留纯 router 层并临时关闭 serve-api 命令。

## Checkpoints
- Commit after: DOCS-009 / CORE-006 / API-001 / APP-008 / TEST-009

## References
- docs/architecture/system-overview.md
- src/pixiv_artist_recsys/config.py
- src/pixiv_artist_recsys/runtime.py
- src/pixiv_artist_recsys/cli.py
- src/pixiv_artist_recsys/storage/repositories.py
