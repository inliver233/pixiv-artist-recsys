# Changelog

## 0.2.0 — 2026-07-14 (local v1 freeze)

个人本地可用冻结版：真 token 路径可诊断、可采样限流、可分步长跑、多源召回 + 质量排序。

### Added
- Token 轮换闭环：刷新优先使用 DB `refresh_token_rotated`
- 采样上限：`max_seed_artists` / `max_candidate_artists` 贯通 pipeline / CLI / API / jobs
- 多源召回：`user_related` + `illust_related` + `user_recommended` + `tag_search`
- Rank 质量：median bookmarks / consistency / bookmark-view ratio
- HTTP retry/backoff（429/5xx，`RetryingHttpTransport`）
- 分步 CLI：`sync-following`、`hydrate-followed-illusts --no-sync-following`、`build-candidates`、`hydrate-candidate-illusts`、`recommend-from-store` 过滤参数
- Job 示例：`examples/manifest-daily.json`、`examples/manifest-deep.json`
- 运维文档：`docs/ops/step-pipeline-and-troubleshooting.md`
- 实网自测清单：`docs/ops/live-checklist.md`
- Backlog：`docs/backlog.md`

### Changed
- CLI / facade / job 默认 `followed_artist_limit=8`、`candidate_artist_limit=5`（对齐日常推荐档）
- README / system-overview / 计划书与代码对齐

### Security
- `.env` / sqlite / 真 token 默认不入库；示例仅占位符

## 0.1.0 — 骨架期

12 批 Issue 完成的核心链路：Auth → Following → Hydrate → Profile → Related → Rank → Feedback → Audit；CLI / 本地 API / Job Manifest。
