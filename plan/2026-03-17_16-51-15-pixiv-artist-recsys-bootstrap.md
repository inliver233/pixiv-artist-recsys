---
mode: plan
task: Pixiv Artist Recsys Bootstrap
created_at: "2026-03-17T16:51:15+08:00"
complexity: complex
---

# Plan: Pixiv Artist Recsys Bootstrap

## Goal
- 在本地建立 `pixiv-artist-recsys` 仓库、调查资产、Issue CSV 工作流和首版推荐系统代码骨架。

## Scope
- In:
  - 调查当前工作区与 `.codex/` 工作流资产
  - 建立 repo-local plan / issue csv / investigation csv
  - 初始化本地 Git 与 `test` 分支
  - 搭建 Python 项目骨架、SQLite 存储、服务接口与 CLI
- Out:
  - 真实 Pixiv API 登录联调
  - 代理池生产化实现
  - 完整推荐算法与线上部署

## Assumptions / Dependencies
- 现有仓库调查报告《基于pixiv的推荐系统pid获取详细调查报告.md》可作为参考输入。
- 首版优先本地单机、单进程、本地 SQLite。
- 当前阶段只使用本地 Git，不配置远端。

## Phases
1. 建立仓库工作流资产与计划/Issue CSV。
2. 沉淀调查矩阵与系统架构文档。
3. 搭建源码骨架、领域模型与本地存储。
4. 搭建推荐流程接口、CLI 与基础测试。
5. 为后续 token/proxy/pixiv client 实现预留明确接口与 issue。

## Tests & Verification
- 工作流文件齐全 -> `Get-ChildItem .codex,docs,issues,plan`
- Issue CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_16-51-15-pixiv-artist-recsys-bootstrap.csv`
- 代码骨架可导入 -> `python -m compileall -q src tests`
- 基础单测可跑 -> `python -m unittest -v`

## Issue CSV
- Path: issues/2026-03-17_16-51-15-pixiv-artist-recsys-bootstrap.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：当前阶段以本地 shell + Python 脚本为主
- chrome-devtools：后续 UI / Web 流程调试时使用
- context7：后续查框架文档时使用

## Acceptance Checklist
- [x] 本地仓库已初始化并切换到 `test` 分支
- [x] 已生成调查 CSV、架构文档、Plan、Issue CSV
- [x] 已建立 Python 代码骨架与本地存储骨架
- [x] 已建立 CLI 与最小测试
- [x] 已明确后续 issue 路线图

## Risks / Blockers
- Pixiv API/登录协议未来可能变化
- 当前阶段尚未接入真实 token/proxy，接口层只能先做抽象
- 若后续选择外部依赖框架，需要补充依赖管理与安装脚本

## Rollback / Recovery
- 若框架拆分不合理，可保留 docs/plan/issues 不变，仅回滚 `src/` 与 `tests/` 的当前增量。
- 若本地 schema 不满足后续需求，可在后续 issue 中添加 migration 方案。

## Checkpoints
- Commit after: BOOT-001 / DOCS-001 / CORE-001 / CORE-002 / CORE-003 / APP-001 / TEST-001

## References
- 基于pixiv的推荐系统pid获取详细调查报告.md
- AGENTS.md
- .codex/skills/plan/
- docs/testing-policy.md
- issues/README.md
