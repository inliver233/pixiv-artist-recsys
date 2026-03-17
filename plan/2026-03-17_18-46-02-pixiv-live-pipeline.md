---
mode: plan
task: Pixiv Live Pipeline
created_at: "2026-03-17T18:46:02+08:00"
complexity: complex
---

# Plan: Pixiv Live Pipeline

## Goal
- 从“分步本地能力”推进到“单次执行可完成 following -> hydration -> profile -> candidate -> candidate hydration -> rank -> 输出 UID”的可运行闭环。

## Scope
- In:
  - 增加 candidate artists 的作品补水能力
  - 增加 live recommendation pipeline orchestration
  - 扩展 CLI 支持 full-recommend
  - 更新路线图文档与 issue 资产
- Out:
  - proxy pool / failover 真实实现
  - feedback loop / negative feedback 持久化
  - Web API / worker queue

## Assumptions / Dependencies
- 继续使用本地 SQLite。
- 继续允许 fake Pixiv client 做单测。
- 通过 refresh token / access token 或 patch 方式驱动 CLI；真实联调留在后续批次继续强化。

## Phases
1. 生成第四批 plan 与 issue CSV，并更新架构路线图。
2. 实现 candidate artist hydration。
3. 实现 live pipeline orchestration。
4. 扩展 CLI 支持 full-recommend。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_18-46-02-pixiv-live-pipeline.csv`
- Candidate hydration -> `python -m unittest -v tests.test_hydration.CandidateHydrationTests`
- Live pipeline -> `python -m unittest -v tests.test_live_pipeline.LivePipelineTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_18-46-02-pixiv-live-pipeline.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续以本地 Python + fake client 测试推进

## Acceptance Checklist
- [x] 已生成第四批 plan 与 Issue CSV
- [x] 已实现 candidate artist hydration
- [ ] 已实现 live recommendation pipeline
- [ ] 已实现 CLI full-recommend 命令
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 当前 candidate hydration 仍按少量代表作抽样，后续需补充更多质量统计。
- 若真实 Pixiv related / user_illusts 限流明显，后续需尽快接入 proxy/failover。

## Rollback / Recovery
- 若 live pipeline 设计不稳定，可保留 ingest/profile/candidate/rank 单体服务，单独回滚 orchestration 层。

## Checkpoints
- Commit after: DOCS-004 / INGEST-003 / PIPE-001 / APP-003 / TEST-004

## References
- docs/architecture/system-overview.md
- docs/architecture/issue-map.md
- src/pixiv_artist_recsys/ingest/artist_illust_hydration.py
- src/pixiv_artist_recsys/candidate/service.py
- src/pixiv_artist_recsys/rank/service.py
