---
mode: plan
task: Pixiv Runtime Diversity Export
created_at: "2026-03-17T19:48:04+08:00"
complexity: complex
---

# Plan: Pixiv Runtime Diversity Export

## Goal
- 继续增强整体架构质量与可维护性：引入统一 runtime 装配层、diversity-aware 排序，以及 run 列表/导出能力。

## Scope
- In:
  - 生成第八批 plan / issue 资产并更新路线图
  - 实现统一 AppRuntime / wiring container
  - 实现 diversity-aware ranking
  - 扩展 CLI 支持 list-runs / export-run，并接入 runtime
- Out:
  - Web 服务层
  - 分布式任务调度
  - embedding / LLM rerank

## Assumptions / Dependencies
- 继续使用本地 SQLite。
- 继续使用当前启发式分数，diversity 作为后处理选择层。
- 导出格式优先 JSON。

## Phases
1. 生成第八批 plan 与 issue CSV，并更新架构文档。
2. 实现 AppRuntime 统一装配与基础测试。
3. 实现 diversity-aware rank。
4. 扩展 CLI 支持 list-runs / export-run，并切换到 runtime 装配。
5. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_19-48-04-pixiv-runtime-diversity-export.csv`
- Runtime -> `python -m unittest -v tests.test_runtime.RuntimeTests`
- Diversity rank -> `python -m unittest -v tests.test_rank.RankServiceTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_19-48-04-pixiv-runtime-diversity-export.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地实现 + fake 测试

## Acceptance Checklist
- [x] 已生成第八批 plan 与 Issue CSV
- [x] 已实现统一 runtime 装配层
- [x] 已实现 diversity-aware ranking
- [x] 已实现 run 列表/导出 CLI 与 runtime 接入
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- diversity 后处理若设置过强，可能压低整体分数最优性。
- 导出 JSON 结构需要后续稳定化以方便外部消费。

## Rollback / Recovery
- 若 runtime 重构引入问题，可保留 CLI 旧调用方式并逐步迁移。

## Checkpoints
- Commit after: DOCS-008 / CORE-005 / RANK-004 / APP-007 / TEST-008

## References
- docs/architecture/system-overview.md
- src/pixiv_artist_recsys/runtime.py
- src/pixiv_artist_recsys/rank/service.py
- src/pixiv_artist_recsys/cli.py
- src/pixiv_artist_recsys/storage/repositories.py
