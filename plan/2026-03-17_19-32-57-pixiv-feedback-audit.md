---
mode: plan
task: Pixiv Feedback Audit
created_at: "2026-03-17T19:32:57+08:00"
complexity: complex
---

# Plan: Pixiv Feedback Audit

## Goal
- 增加反馈闭环与推荐审计，使推荐结果可追溯、可调优，并能基于 dislike/block 信号抑制后续垃圾候选。

## Scope
- In:
  - 生成第七批 plan / issue 资产并更新路线图
  - 增加 feedback events / negative profile 存储与服务
  - 增加 recommendation run audit 持久化
  - 在 rank 中接入 negative feedback suppression
  - CLI 增加 feedback / audit 查询命令
- Out:
  - Web 控制台
  - 实时流式反馈训练
  - embedding / LLM rerank

## Assumptions / Dependencies
- 继续使用本地 SQLite。
- 负反馈先基于标签与明确 block/dislike 做规则抑制。
- run audit 先以 JSON summary 持久化，后续再拆更细粒度指标表。

## Phases
1. 生成第七批 plan 与 issue CSV，并更新架构文档。
2. 实现 feedback events 与 negative profile。
3. 实现 run audit 持久化，并接入 live pipeline。
4. 实现 negative feedback suppression 与 CLI 查询命令。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_19-32-57-pixiv-feedback-audit.csv`
- Feedback -> `python -m unittest -v tests.test_feedback.FeedbackServiceTests`
- Rank suppression -> `python -m unittest -v tests.test_rank.RankServiceTests`
- Live pipeline audit -> `python -m unittest -v tests.test_live_pipeline.LivePipelineTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_19-32-57-pixiv-feedback-audit.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地实现 + fake client 测试

## Acceptance Checklist
- [x] 已生成第七批 plan 与 Issue CSV
- [ ] 已实现 feedback events / negative profile
- [ ] 已实现 run audit persistence
- [ ] 已实现 negative feedback suppression 与 CLI 查询
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 当前 negative profile 仍是规则版，后续还需引入更细粒度画像。
- audit 以 JSON 存储，可读性高但 SQL 聚合能力有限。

## Rollback / Recovery
- 若 suppression 过强，可保留 feedback/audit 存储，仅回滚 rank 中的负反馈惩罚逻辑。

## Checkpoints
- Commit after: DOCS-007 / FEED-001 / AUDIT-001 / RANK-003 / APP-006 / TEST-007

## References
- docs/architecture/system-overview.md
- src/pixiv_artist_recsys/storage/schema.py
- src/pixiv_artist_recsys/rank/service.py
- src/pixiv_artist_recsys/pipeline/live_recommendation.py
- src/pixiv_artist_recsys/cli.py
