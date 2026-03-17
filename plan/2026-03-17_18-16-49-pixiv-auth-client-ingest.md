---
mode: plan
task: Pixiv Auth Client Ingest
created_at: "2026-03-17T18:16:50+08:00"
complexity: complex
---

# Plan: Pixiv Auth Client Ingest

## Goal
- 在当前骨架基础上落地第二批核心实现：Pixiv OAuth refresh、access token cache、Pixiv App API client、following ingest 服务与对应测试。

## Scope
- In:
  - auth 配置、签名头、refresh token 请求构造与响应解析
  - access token cache 与本地 token 元数据持久化
  - Pixiv App API client（following / user detail / user illusts / illust detail）
  - following ingest service 与数据库写入
  - 对应 CLI/测试扩展
- Out:
  - 多 token 调度
  - 代理池/failover 真实实现
  - ranking / profile 的真实算法增强

## Assumptions / Dependencies
- 继续使用本地 SQLite 和标准库优先。
- 真实 Pixiv 网络调用通过可替换 transport 抽象实现，测试中使用 fake transport。
- 当前阶段不写入真实 token 明文，默认只存 masked ref / rotated metadata。

## Phases
1. 生成第二批 plan 与 issue CSV。
2. 实现 auth service、token models、cache 与 token 表。
3. 实现 Pixiv App API client 与 DTO 解析。
4. 实现 following ingest 服务与持久化。
5. 扩展测试、完成本地回归与 issue 状态同步。

## Tests & Verification
- CSV 合法 -> `python .codex/skills/plan/scripts/validate_issues_csv.py issues/2026-03-17_18-16-49-pixiv-auth-client-ingest.csv`
- Auth 逻辑 -> `python -m unittest -v tests.test_auth`
- Pixiv client -> `python -m unittest -v tests.test_pixiv_client`
- Ingest 服务 -> `python -m unittest -v tests.test_ingest`
- 全量回归 -> `python -m unittest -v` + `python -m compileall -q src tests`

## Issue CSV
- Path: issues/2026-03-17_18-16-49-pixiv-auth-client-ingest.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none：当前批次主要为本地 Python 实现与 fake transport 测试

## Acceptance Checklist
- [x] 已生成第二批 plan 与 Issue CSV
- [x] 已实现可测试的 OAuth refresh service 与 token cache
- [x] 已实现 Pixiv App API client 关键端点
- [x] 已实现 following ingest 服务与本地存储写入
- [x] 全量 unittest 与 compileall 通过

## Risks / Blockers
- Pixiv 移动端请求头未来可能变化
- 当前未接真实代理与 failover，后续联调时可能需调整 transport 抽象
- 真实 API 分页/错误码细节可能需要在后续联调中补齐

## Rollback / Recovery
- 若真实 Pixiv 接口设计与当前抽象不符，可保留 DTO / repository，不兼容部分回滚 `auth/` `pixiv/` `ingest/` 模块增量。

## Checkpoints
- Commit after: DOCS-002 / AUTH-001 / AUTH-002 / PIXIV-001 / INGEST-001 / TEST-002

## References
- docs/architecture/token-proxy-pixiv-interface-map.md
- docs/investigation/pixiv_capability_matrix.csv
- ../Random-image-api/backend/app/pixiv/oauth.py
- ../pixiv-downloader/common/PixivAppApi.py
- ../pixiv-viewer/src/api/client/pixiv-api.js
