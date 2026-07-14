# System Overview

## Product goal

输入 Pixiv refresh token 与用户偏好，输出符合已关注审美、尚未关注、质量足够高的画师 UID 列表。

## Core pipeline

1. Auth: refresh token / access token 管理（DB 优先 rotated refresh）
2. Ingest: 同步关注 + 代表作 hydrate（`max_seed_artists` 上限）
3. Profile: tags / tag pairs / negative profile
4. Candidate: multi-source 召回（`max_seed_artists` 控制种子规模；CLI `build-candidates`）
5. Hydrate: 候选画师作品（`max_candidate_artists` 上限；CLI `hydrate-candidate-illusts`）
6. Rank: quality + taste + diversity + feedback suppression（CLI `recommend-from-store`）
7. Feedback / Audit: 事件回流 + run 审计快照

分步 CLI 可独立重跑：`sync-following` → `hydrate-followed-illusts`（`--no-sync-following`）→ `build-profile` → `build-candidates` → `hydrate-candidate-illusts` → `recommend-from-store`。详见 `docs/ops/step-pipeline-and-troubleshooting.md`。

## Implemented baseline

- OAuth refresh / token cache / token coordinator（prefer `refresh_token_rotated`）
- Pixiv App API client（following / user detail / user illusts / illust detail / user related / illust related / user recommended / search illust）
- following sync、followed / candidate hydration、taste profile
- multi-source candidate retrieval：user_related + illust_related + user_recommended + tag_search + seed_artist_following（公开关注抽样，默认 18×28）
- heuristic rank with median bookmarks / consistency / diversity / feedback suppression
- live pipeline：`following -> hydration -> profile -> candidate -> candidate hydration -> rank`
- quality guardrails：allow AI / allow R18 / min bookmarks / min score（默认 min_score 0.52）
- HTTP retry/backoff（429 Retry-After + jitter）+ outbound pace（~0.12s）+ proxy failover
- hydrate 在 user_illusts list 已含 tags 时跳过 illust/detail；大关注列表 hash 抽样种子
- typed settings、本地 JSON API、ApplicationFacade、CLI/API/jobs 共用
- sampling caps：`max-seed-artists` / `max-candidate-artists`（精准日常默认 90 / 130）

## Module map

- `config.py`: typed settings / env helpers
- `runtime.py`: unified runtime / wiring
- `application/`: facade for CLI/API/jobs
- `jobs/`: seed job + manifest
- `auth/`: OAuth / cache / coordinator / transport
- `proxy/`: proxy pool / failover transport
- `pixiv/`: App API client / inspector / DTO
- `ingest/`: following + hydration（artist caps）
- `profile/`: taste profile
- `candidate/`: related retrieval（seed caps）
- `rank/`: heuristic rank + guardrails
- `feedback/`: events / negative profile
- `storage/`: SQLite schema / repository
- `pipeline/`: dry-run + live orchestration
- `api/`: local JSON API
- `cli.py`: command entry

## Sampling controls

| Param | Default | Role |
|-------|--------:|------|
| `followed_artist_limit` | 10 | 每位关注画师拉取 illust 数（精准日常默认） |
| `candidate_artist_limit` | 6 | 每位候选画师拉取 illust 数（精准日常默认） |
| `max_related_per_artist` | 6 | 每位种子 user_related 上限 |
| `max_related_per_illust` | 6 | 每张图 illust_related 上限 |
| `max_seed_artists` | 90 | 参与 hydrate/召回的关注画师上限（hash 抽样） |
| `max_candidate_artists` | 130 | 需要 hydrate 的候选画师上限 |
| `enable_seed_following` | true | 从已关注画师的公开关注列表扩展候选 |
| `max_seed_following_artists` | 18 | 扩展多少个种子画师（抽样，非全量） |
| `max_following_per_seed_artist` | 28 | 每个种子最多取多少公开关注 |
| `seed_following_sample` | hydrated_first | 种子挑选：hydrated_first / hash / first |
| `max_results` | 60 | 最终输出条数 |
| `min_score` | 0.52 | 排序最低分（防弱证据刷榜） |
| `diversity_per_tag` | 3 | 主 tag 多样性上限 |
| HTTP pace min interval | 0.12s | 单 token 稳态间隔（env 可关） |

## Roadmap status

- Phase 1–12: dry-run → live pipeline → guardrails → proxy → feedback → runtime → API → jobs ✅
- M0/M1: token 轮换、采样上限、错误可诊断、文档 ✅
- M2: multi-source recall + rank quality + HTTP retry ✅
- M3: 分步 CLI + manifest 示例 + ops 故障表 ✅
- M4: live checklist / CHANGELOG / `0.2.0` / backlog ✅
