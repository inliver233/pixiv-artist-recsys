---
mode: plan
task: Pixiv Proxy Failover
created_at: "2026-03-17T19:23:33+08:00"
complexity: complex
---

# Plan: Pixiv Proxy Failover

## Goal
- 为 OAuth 与 Pixiv App API 接入可维护的代理池与失败切换能力，降低单代理失效导致的全链路失败概率。

## Scope
- In:
  - 生成第六批 plan / issue 资产并更新路线图
  - 实现 proxy pool / health state / cooldown policy
  - 实现 failover transport 并接入 OAuth 与 Pixiv client 构建链路
  - CLI 增加 proxy state 输出
- Out:
  - 分布式代理状态持久化
  - 第三方代理供应商对接
  - 代理自动测速与地域调度

## Assumptions / Dependencies
- 默认仍可直连；代理池为可选能力。
- 代理列表先通过环境变量注入。
- 失败切换策略先采用本地进程内状态。

## Phases
1. 生成第六批 plan 与 issue CSV，并更新架构文档。
2. 实现 proxy pool、health policy 与 failover transport。
3. 接入 CLI 构建链路并提供 proxy state 可视化。
4. 运行本批回归并同步 CSV / plan。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_19-23-33-pixiv-proxy-failover.csv`
- Proxy failover -> `python -m unittest -v tests.test_proxy.ProxyTransportTests`
- CLI -> `python -m unittest -v tests.test_cli.CLITests`
- 全量回归 -> `python -m unittest -v && python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_19-23-33-pixiv-proxy-failover.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：继续使用本地实现 + fake transport 测试

## Acceptance Checklist
- [x] 已生成第六批 plan 与 Issue CSV
- [ ] 已实现 proxy pool / failover transport
- [ ] 已实现 CLI proxy state / build chain integration
- [ ] 全量 unittest 与 compileall 通过

## Risks / Blockers
- 当前 proxy 状态仅在单进程内维护，跨进程不会共享。
- 若真实代理要求账号密码，后续需补充更完整的解析与脱敏展示。

## Rollback / Recovery
- 若 proxy policy 不稳定，可保留 direct transport，并将 failover transport 作为可选层回退。

## Checkpoints
- Commit after: DOCS-006 / PROXY-001 / APP-005 / TEST-006

## References
- docs/architecture/system-overview.md
- src/pixiv_artist_recsys/auth/transport.py
- src/pixiv_artist_recsys/auth/service.py
- src/pixiv_artist_recsys/pixiv/client.py
- src/pixiv_artist_recsys/cli.py
