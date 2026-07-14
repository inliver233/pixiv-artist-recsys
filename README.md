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

# 一键 full-recommend（默认 daily 预设：max_seed=90 / max_candidate=130）
python start.py run

# 分步：母号只 sync 关注一次，已有关注边时可跳过
python start.py steps

# 从 downloader 重导配置
python start.py import-config
```

预设：`quick` / `daily`（默认，约 2600 关注的精准档） / `deep`。结果写入 `data/local/exports/`（gitignore）。

`run` / `steps` 会实时打印阶段进度（关注分页、水合作者计数、召回进度条等）；关注全量同步约 2600 人时不再“卡住无输出”。

单子号 token 下默认 **深度采样 + 稳态 pacing**（非真并发）：HTTP 最小间隔约 0.12s + 抖动，429 尊重 Retry-After；hydrate 在 list 已带 tags 时跳过 illust/detail，降低 API 量。

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
- 排序 v2：profile 去噪+IDF、题材 exact/子串+占比过滤、`illust_type`/`page_count`、校准分（无 ×40），默认 `min_score=0.28` / `min_local_illusts=2`。
- 失败时 OAuth/App API 错误会带 status 与 body 摘要，便于诊断 401/429。
- 风控相关 env：`PIXIV_ARTIST_RECSYS_HTTP_MIN_INTERVAL_S`（默认 0.12）、`PIXIV_ARTIST_RECSYS_HTTP_PACE_JITTER_S`、`PIXIV_ARTIST_RECSYS_HTTP_PACE_ENABLED`、`PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS` / `HTTP_RETRY_*`。

### 日常 vs 深度（建议 / `start.py` 预设）

| 档位 | max-seed | max-candidate | seed-following 画师数 | 每画师公开关注 | max-results | min_score |
|------|--------:|--------------:|---------------------:|--------------:|------------:|----------:|
| quick | 40 | 70 | 6 | 12 | 40 | 0.28 |
| daily | 90 | 130 | 12 | 18 | 60 | 0.28 |
| deep | 140 | 200 | 18 | 24 | 80 | 0.24 |

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
