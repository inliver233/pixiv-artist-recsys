---
mode: plan
task: Pixiv Quality Guardrails
created_at: "2026-03-17T18:57:08+08:00"
complexity: complex
---

# Plan: Pixiv Quality Guardrails

## Goal
- 在已跑通 live pipeline 的基础上，加上 seed-user 偏好持久化与质量护栏，减少 AI/R18/低质量候选，逼近“不是烂图、不是垃圾”的目标。

## Scope
- In:
  - seed user allow_ai / allow_r18 偏好读取与 following sync 保持
  - rank 层增加 AI/R18 / low-bookmark / min-score guardrails
  - live pipeline / CLI 暴露质量过滤参数
  - 回归测试与文档同步
- Out:
  - 代理池 / failover
  - 用户显式 dislike / block 反馈学习
  - embedding / 深度排序模型

## Assumptions / Dependencies
- 继续使用本地 SQLite。
- 本批 guardrails 仍基于规则，不引入模型推理。
- 低质量阈值由 CLI 传入并可调。

## Phases
1. 生成第五批 plan 与 issue CSV，并更新路线图。
2. 实现 seed user 偏好持久化与 following sync 保持。
3. 实现 rank guardrails 并接入 live pipeline。
4. 扩展 CLI full-recommend 暴露质量过滤参数。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_18-57-08-pixiv-quality-guardrails.csv`
- Core preference persistence -> `python -m unittest -v tests.test_ingest.IngestTests`
- Rank guardrails -> `python -m unittest -v tests.test_rank.RankServiceTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_18-57-08-pixiv-quality-guardrails.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地实现 + fake client 测试

## Acceptance Checklist
- [x] 已生成第五批 plan 与 Issue CSV
- [x] 已实现 seed user 偏好持久化
- [ ] 已实现 rank quality guardrails
- [ ] 已实现 CLI 质量过滤参数
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 仅靠 bookmarks / AI / x_restrict 规则仍不足以完全解决审美偏差。
- 后续仍需 negative feedback 与 diversity 补强。

## Rollback / Recovery
- 若 guardrails 误杀太多候选，可保留参数接口，仅回滚默认阈值。

## Checkpoints
- Commit after: DOCS-005 / CORE-004 / RANK-002 / APP-004 / TEST-005

## References
- docs/architecture/system-overview.md
- src/pixiv_artist_recsys/ingest/following_sync.py
- src/pixiv_artist_recsys/rank/service.py
- src/pixiv_artist_recsys/pipeline/live_recommendation.py
- src/pixiv_artist_recsys/cli.py
