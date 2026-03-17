---
mode: plan
task: Pixiv Job Runner Manifest
created_at: "2026-03-17T20:33:50+08:00"
complexity: medium
---

# Plan: Pixiv Job Runner Manifest

## Goal
- 继续增强稳定运行能力：引入本地 job runner 与 manifest 批处理，让推荐任务可按配置批量执行并产出本地快照。

## Scope
- In:
  - 生成第十一批 plan / issue 资产并更新路线图
  - 实现 jobs runner / manifest 读取 / 输出快照
  - CLI 增加 run-seed-job / run-manifest
  - 为批处理与快照输出补齐测试
- Out:
  - 分布式调度
  - 定时器守护进程
  - 云端任务编排

## Assumptions / Dependencies
- manifest 先使用 JSON。
- 输出快照先写入本地文件系统。
- job runner 基于现有 ApplicationFacade。

## Phases
1. 生成第十一批 plan 与 issue CSV，并更新架构文档。
2. 实现 jobs runner 与 manifest parser。
3. 扩展 CLI run-seed-job / run-manifest。
4. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_20-33-50-pixiv-job-runner-manifest.csv`
- Jobs -> `python -m unittest -v tests.test_jobs.JobRunnerTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_20-33-50-pixiv-job-runner-manifest.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地 JSON + fake client 测试

## Acceptance Checklist
- [x] 已生成第十一批 plan 与 Issue CSV
- [x] 已实现 jobs runner / manifest parser
- [x] 已实现 CLI run-seed-job / run-manifest
- [x] 全量 unittest 与 compileall 通过

## Risks / Blockers
- manifest 中含 token 时需要确保仅本地使用。
- 批处理时单个 job 失败的恢复策略要明晰。

## Rollback / Recovery
- 若批处理入口不稳定，可先保留单 job runner 并暂时关闭 manifest 命令。

## Checkpoints
- Commit after: DOCS-011 / CORE-008 / APP-010 / TEST-011

## References
- src/pixiv_artist_recsys/application/facade.py
- src/pixiv_artist_recsys/cli.py
- docs/architecture/system-overview.md
