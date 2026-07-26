# Changelog

## Unreleased (dev) — 2026-07-26 起，S0+Q0 性能与质量基建

调查报告《未来升级方向.md》阶段一落地：暖库轮次成本数量级下降 + 排序信号升级 + 反馈闭环产品层。

### Performance
- SQLite：WAL + synchronous=NORMAL + busy_timeout、批量事务、`idx_illusts_user_id` 索引、全链路 N+1 改单条聚合 SQL、`PRAGMA user_version` 迁移框架
- HTTP：keep-alive 连接池替代每请求新建 opener（P-1）；**pacing 同步收紧至 ~1 req/s**（保号硬约束）；补 PixivAndroidApp User-Agent / App-OS / App-Version 头；JSON body "Rate Limit" 视同 429 退避；pacing 移入 retry 内层使每次尝试都被限速
- illust_related：独立参数 `max_illusts_for_related`（默认 4）+ `seed_illust_ids[]` 批量种子接口（每种子画师一个请求）+ 7 天 TTL 缓存表
- skip-if-fresh：illusts/artists 加时间戳列，TTL 内画师不重抓（`FRESHNESS_DAYS`，默认 10 天）；following 同步支持 24h 内跳过与"连续 N 个已知 ID 早停"；seed_following 翻页上限 4 页
- 水合循环单画师 try/except 容错：一个 404 不再报废整轮

### Quality（排序 v5）
- 修子串误杀：manga/furry/BL 从硬屏蔽降级为题材占比软惩罚（'ケモ' 曾误杀 ケモミミ 画师）；AI 标记保持硬屏蔽
- co-follow 独立特征（distinct seed_artist_following source_key 计数），权重 0.20
- 档次门：candidate median ≥ followed P40 × ratio（单作爆款不再过门）；ratio 0.35→0.45；taste_floor=0.12 硬门；evidence 降权至 0.08
- 画像：follow 正反馈并入、时间衰减 exp(-days/180)、质量加权 TF（log1p(max_bm)）
- 曝光去重：recommended_history 表 + (1-0.5)*0.9^n+0.5 重复展示降权
- 采样 salt 默认按日轮换（探索面不再固化）

### Evaluation & Product
- 留一法离线评估框架（`evaluate-offline`）：Recall@50 / NDCG@20，全量排序无负采样；本地实测 Q0 改动 recall@50 0.044→0.074、ndcg@20 0.033→0.086
- HTML 报告导出（`export-run-html` / `start.py run` 自动生成）：画师卡片+缩略图+一键 dislike/block 回写本地 API；API 加 localhost/file CORS

### v3/v4 里程碑补记（曾漏记，代码在 41bf2b4 / a183b0c）
- v3（a183b0c）：profile IDF 与去噪、校准排序分、题材 exact/子串/占比过滤、`illust_type`/`page_count` 门
- v4（41bf2b4）：mega 级预设（seed 400-1200 / candidate 1000-4000）、campaign 多轮共识（`rank/consensus.py`）、`start.py` 启动器与 5 套预设、母/子双 token 分离、downloader 配置导入

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
