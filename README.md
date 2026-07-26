# pixiv-artist-recsys

本地运行的 Pixiv 画师推荐 UID 获取系统：输入 refresh token，输出符合已关注审美、尚未关注的画师列表。

仓库：https://github.com/inliver233/pixiv-artist-recsys

## 当前状态（2026-07-14）

- 版本：**0.2.0**（本地全量可用冻结，见 `CHANGELOG.md`）
- 12 批 Issue 已完成，核心链路可跑：Auth → Following → Hydrate → Profile → 多源召回 → Rank → Feedback → Audit
- 入口：CLI / 本地 JSON API / Job Manifest / 分步长跑
- 测试：标准库 `unittest`（无第三方依赖）
- 路线图：`计划书.md`；后续项：`docs/backlog.md`

## 目录

| 路径 | 说明 |
|------|------|
| `src/pixiv_artist_recsys/` | 源码 |
| `tests/` | 单元测试 |
| `docs/architecture/` | 架构与接口图 |
| `plan/` `issues/` | 历史实施计划与 CSV |
| `data/` | 本地数据（默认不入库） |
| `计划书.md` | 全量可用推进 SSOT |

## 快速开始

```powershell
cd pixiv-artist-recsys
python -m compileall -q src tests
python -m unittest -v
python -m pixiv_artist_recsys init-db
python -m pixiv_artist_recsys show-config
```

复制 `.env.example` 按需设置路径/推荐阈值（**不要**把真实 refresh token 写进仓库）。

### 本机启动器 `start.py`（状态检测 + 一键运行）

适合已从 `pixiv-downloader-personal` 导入母号/子号/代理的本机环境（关注数约 2000+ 时默认用抽样上限）：

```powershell
# 自动加载 .env，打印 token/母子号/代理/库内关注边等状态
python start.py status

# 交互菜单
python start.py

# 一键 full-recommend（默认 daily 预设：max_seed=400 / max_candidate=1000）
python start.py run

# 分步：母号只 sync 关注一次，已有关注边时可跳过
python start.py steps

# 从 downloader 重导配置
python start.py import-config
```

预设：`quick` / `daily`（默认） / `deep` / `mega` / `campaign`。结果写入 `data/local/exports/`（gitignore），同时生成可浏览的 `full-<run_id>.html` 报告（画师卡片 + 缩略图 + 一键 dislike/block，反馈按钮需 `serve-api` 运行中）。

`run` / `steps` 会实时打印阶段进度（关注分页、水合作者计数、召回进度条等）。

单子号 token 下默认 **稳态 pacing ~1 req/s**（连接复用后不可跑满 0.12s 间隔，撞社区安全线）：HTTP keep-alive 连接池 + 最小间隔 1.0s + 抖动，429/JSON body Rate Limit 均触发退避；hydrate 在 list 已带 tags 时跳过 illust/detail；skip-if-fresh 使第二轮起只抓过期/新增画师；following 同步支持增量早停与 24h 内跳过。

### 一键推荐（需要真实 refresh token）

```powershell
python -m pixiv_artist_recsys full-recommend `
  --seed-user-id <你的 pixiv user id> `
  --refresh-token <refresh_token> `
  --followed-artist-limit 10 `
  --candidate-artist-limit 6 `
  --max-related-per-artist 6 `
  --max-related-per-illust 6 `
  --max-seed-artists 90 `
  --max-candidate-artists 130 `
  --max-results 60
```

说明：

- **rotated refresh token** 会写入 SQLite；下次刷新优先用库里的新 token，即使 CLI 仍传旧值。
- `--max-seed-artists` / `--max-candidate-artists` 限制 hydrate/召回规模，避免关注数很大时 API 爆炸；大关注列表用 hash 抽样轮换种子。
- 候选多源：`user_related` / `illust_related` / `user_recommended` / `tag_search` / **`seed_artist_following`**（从你已关注画师的**公开关注列表**抽样扩展，默认开启、权重 0.55，避免 following 洪水）。
- 种子关注扩展可控：`--max-seed-following-artists`（默认 12）× `--max-following-per-seed-artist`（默认 18），采样 `--seed-following-sample random|hydrated_first|hash|first`；**不做全图爬取**。
- 排序 v5：profile 去噪+IDF+时间衰减+质量加权、co-follow 独立特征（0.20 权重）、taste_floor 硬门（0.12）、median 相对档次门（followed P40 × 0.45）、题材占比软过滤（AI 标记仍硬屏蔽）、曝光去重降权，默认 `min_score=0.24` / `min_local_illusts=2`。
- 离线评估：`evaluate-offline --seed-user-id <id>` 留一法 Recall@50 / NDCG@20（纯本地，零 API），调参前后各跑一次对比。
- 失败时 OAuth/App API 错误会带 status 与 body 摘要，便于诊断 401/429。
- 风控相关 env：`PIXIV_ARTIST_RECSYS_HTTP_MIN_INTERVAL_S`（默认 1.0，连接复用后请勿调低）、`PIXIV_ARTIST_RECSYS_HTTP_PACE_JITTER_S`、`PIXIV_ARTIST_RECSYS_HTTP_PACE_ENABLED`、`PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS` / `HTTP_RETRY_*`、`PIXIV_ARTIST_RECSYS_FRESHNESS_DAYS`（hydrate skip-if-fresh TTL，默认 10）。

### `start.py` 预设（v4，真实值见 `start.py` PRESETS）

| 档位 | max-seed | max-candidate | seed-following 画师数 | 每画师公开关注 | max-results | min_score |
|------|--------:|--------------:|---------------------:|--------------:|------------:|----------:|
| quick | 200 | 400 | 24 | 30 | 200 | 0.24 |
| daily | 400 | 1000 | 48 | 40 | 500 | 0.24 |
| deep | 700 | 1800 | 80 | 50 | 1000 | 0.24 |
| mega | 1200 | 4000 | 120 | 60 | 2000 | 0.24 |
| campaign | 500 | 1500 | 80 | 50 | 2000/轮 | 0.24 |

另有 `max_illusts_for_related=4`（批量 illust_related 种子数，HTTP 成本旋钮）与 `min_relative_bookmark_ratio=0.45`（相对档次门）等共通参数。

### 分步长跑（可恢复）

适合关注数较多、需要断点续跑：

```powershell
# Token: --refresh-token 或环境变量 PIXIV_ARTIST_RECSYS_REFRESH_TOKEN（别名 PIXIV_REFRESH_TOKEN 亦可）
python -m pixiv_artist_recsys sync-following --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN
python -m pixiv_artist_recsys hydrate-followed-illusts --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN --max-artists 90 --no-sync-following
python -m pixiv_artist_recsys build-profile --seed-user-id <id>
python -m pixiv_artist_recsys build-candidates --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN --max-seed-artists 90
python -m pixiv_artist_recsys hydrate-candidate-illusts --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN --max-artists 130
python -m pixiv_artist_recsys recommend-from-store --seed-user-id <id> --max-results 60
```

运维说明、代理与故障表：`docs/ops/step-pipeline-and-troubleshooting.md`

### 其它常用命令

```powershell
# 本地 API
python -m pixiv_artist_recsys serve-api

# 离线排序（库内已有数据）
python -m pixiv_artist_recsys recommend-from-store --seed-user-id <id> --max-results 30

# 负反馈
python -m pixiv_artist_recsys record-feedback --seed-user-id <id> --artist-user-id <uid> --action dislike

# 批处理（示例见 examples/manifest-daily.json）
python -m pixiv_artist_recsys run-manifest --manifest examples/manifest-daily.json --output-dir data/exports
```

## 模块地图

```
auth/          OAuth refresh + cache + coordinator + retry transport
proxy/         代理池 + failover
pixiv/         App API client + inspector（含 recommended / search）
ingest/        following sync + artist illust hydration（可限流）
profile/       标签 / 标签对画像
candidate/     related + user_recommended + tag_search + seed_artist_following
rank/          启发式 + median/consistency + AI/R18/收藏门槛 + 多样性 + 负反馈
feedback/      follow / dislike / block
pipeline/      live recommendation
application/   CLI/API 共用 facade
api/           本地 JSON API
jobs/          seed job + manifest
cli.py         命令入口
```

## 安全

- 真实 token / `.env` / sqlite 默认在 `.gitignore`
- 不要把 refresh token 提交到 git 或写进 issue/plan
- 详见 `AGENTS.md`

## Git

- 默认分支：`main`
- 开发分支：`test`
- Remote：`origin` → `https://github.com/inliver233/pixiv-artist-recsys`

## 下一步

M0–M4 已完成（v0.2.0）。本机用 `docs/ops/live-checklist.md` 走实网勾选；增强项见 `docs/backlog.md`。
