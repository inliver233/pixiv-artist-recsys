---
mode: plan
task: Pixiv Application Live API
created_at: "2026-03-17T20:19:08+08:00"
complexity: complex
---

# Plan: Pixiv Application Live API

## Goal
- 继续增强整体架构与可维护性：引入统一应用层 facade，打通 CLI 与本地 API 的共享编排，并补齐 live recommend / hydrate / profile 的 API 入口。

## Scope
- In:
  - 生成第十批 plan / issue 资产并更新路线图
  - 实现统一 application facade
  - 扩展 API 支持 hydrate/profile/full-recommend live 端点
  - 重构 CLI 复用 facade，减少 payload/流程重复
- Out:
  - 外部 Web 框架
  - 分布式队列
  - 鉴权安全网关

## Assumptions / Dependencies
- 保持标准库 + 当前本地 runtime 架构。
- live API 端点仍面向本地环境，允许直接传 refresh/access token。
- CLI 现有行为需保持兼容。

## Phases
1. 生成第十批 plan 与 issue CSV，并更新架构文档。
2. 实现 application facade，统一封装常用编排与 JSON payload。
3. 扩展 API router 支持 hydrate/profile/full-recommend。
4. 重构 CLI 复用 facade，保持参数兼容。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_20-19-08-pixiv-application-live-api.csv`
- Application/API -> `python -m unittest -v tests.test_api.ApiRouterTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_20-19-08-pixiv-application-live-api.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地实现与 fake client 测试

## Acceptance Checklist
- [ ] 已生成第十批 plan 与 Issue CSV
- [ ] 已实现统一 application facade
- [ ] 已实现 API live hydrate/profile/full-recommend 端点
- [ ] 已完成 CLI 对 facade 的复用重构
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 应用层与 CLI/API 复用时需避免打破既有测试 patch 点。
- live API 端点需控制输入校验，避免 token 缺失导致错误不清晰。

## Rollback / Recovery
- 若 facade 重构影响 CLI，可暂时保留 CLI 原实现并仅让 API 使用 facade。

## Checkpoints
- Commit after: DOCS-010 / CORE-007 / API-002 / APP-009 / TEST-010

## References
- src/pixiv_artist_recsys/cli.py
- src/pixiv_artist_recsys/api/router.py
- src/pixiv_artist_recsys/runtime.py
- src/pixiv_artist_recsys/pipeline/live_recommendation.py
