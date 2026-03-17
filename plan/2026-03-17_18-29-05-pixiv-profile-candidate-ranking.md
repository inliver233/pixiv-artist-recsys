---
mode: plan
task: Pixiv Profile Candidate Ranking
created_at: "2026-03-17T18:29:05+08:00"
complexity: complex
---

# Plan: Pixiv Profile Candidate Ranking

## Goal
- 继续从“能取数据”推进到“能基于本地数据构建画像、召回候选、做启发式 artist 排序并输出结果”。

## Scope
- In:
  - 扩展 Pixiv client 以支持 `user_related` / `illust_related`
  - 增加作品标签存储与已关注画师作品补水服务
  - 构建用户审美画像（tag weights + tag pairs）
  - 候选召回与证据持久化
  - artist-level 启发式排序与 CLI 输出
- Out:
  - 代理/failover 真实实现
  - LLM rerank / embedding 模型
  - Web API 服务层

## Assumptions / Dependencies
- 继续使用本地 SQLite。
- 继续使用 fake transport 做单测；真实 Pixiv 联调留待后续。
- 当前排序为规则启发式，不引入外部 ML 依赖。

## Phases
1. 生成第三批 plan 与 issue CSV。
2. 实现已关注画师作品补水与标签入库。
3. 实现画像构建与候选召回。
4. 实现 artist-level 排序与 CLI 命令。
5. 运行全量回归并同步 CSV/plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_18-29-05-pixiv-profile-candidate-ranking.csv`
- Hydration -> `python -m unittest -v tests.test_hydration`
- Profile -> `python -m unittest -v tests.test_profile`
- Candidate + Rank -> `python -m unittest -v tests.test_candidate_rank`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_18-29-05-pixiv-profile-candidate-ranking.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：本批继续以本地 Python 实现与 fake transport 测试为主

## Acceptance Checklist
- [ ] 已生成第三批 plan 与 Issue CSV
- [ ] 已实现 followed-artist illust hydration 与标签入库
- [ ] 已实现 profile build 与 candidate retrieval
- [ ] 已实现 heuristic artist rank 与 CLI 命令
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 若真实 Pixiv related 接口返回结构与假定不同，后续需调整 DTO 解析
- 当前 artist quality 仍是启发式版本，需后续继续强化

## Rollback / Recovery
- 若 profile / rank 设计不合理，可保留 schema 和 ingest 成果，单独回滚服务层与 CLI 增量。

## Checkpoints
- Commit after: DOCS-003 / INGEST-002 / PROFILE-001 / CAND-001 / RANK-001 / APP-002 / TEST-003

## References
- docs/architecture/system-overview.md
- docs/architecture/token-proxy-pixiv-interface-map.md
- ../Pixiv-XP-Pusher/profiler.py
- ../Pixiv-XP-Pusher/fetcher.py
- ../Pixiv-XP-Pusher/filter.py
- ../pixiv-viewer/src/api/client/pixiv-api.js
