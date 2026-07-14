# System Overview

## Product goal

输入 Pixiv refresh token 与用户偏好，输出符合已关注审美、尚未关注、质量足够高的画师 UID 列表。

## Core pipeline

1. Auth: refresh token / access token 管理（DB 优先 rotated refresh）
2. Ingest: 同步关注 + 代表作 hydrate（`max_seed_artists` 上限）
3. Profile: tags / tag pairs / negative profile
4. Candidate: related 召回（`max_seed_artists` 控制种子规模）
5. Hydrate: 候选画师作品（`max_candidate_artists` 上限）
6. Rank: quality + taste + diversity + feedback suppression
7. Feedback / Audit: 事件回流 + run 审计快照

## Implemented baseline

- OAuth refresh / token cache / token coordinator（prefer `refresh_token_rotated`）
- Pixiv App API client（following / user detail / user illusts / illust detail / user related / illust related / user recommended / search illust）
- following sync、followed / candidate hydration、taste profile
- multi-source candidate retrieval：user_related + illust_related + user_recommended + tag_search
- heuristic rank with median bookmarks / consistency / diversity / feedback suppression
- live pipeline：`following -> hydration -> profile -> candidate -> candidate hydration -> rank`
- quality guardrails：allow AI / allow R18 / min bookmarks / min score
- HTTP retry/backoff（429/5xx）+ proxy failover
- typed settings、本地 JSON API、ApplicationFacade、CLI/API/jobs 共用
- sampling caps：`max-seed-artists` / `max-candidate-artists`

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
| `followed_artist_limit` | 5 | 每位关注画师拉取 illust 数 |
| `candidate_artist_limit` | 3 | 每位候选画师拉取 illust 数 |
| `max_related_per_artist` | 5 | 每位种子 user_related 上限 |
| `max_related_per_illust` | 5 | 每张图 illust_related 上限 |
| `max_seed_artists` | 40 | 参与 hydrate/召回的关注画师上限 |
| `max_candidate_artists` | 80 | 需要 hydrate 的候选画师上限 |
| `max_results` | 50 | 最终输出条数 |

## Roadmap status

- Phase 1–12: dry-run → live pipeline → guardrails → proxy → feedback → runtime → API → jobs ✅
- M0/M1: token 轮换、采样上限、错误可诊断、文档 ✅
- M2: multi-source recall + rank quality + HTTP retry ✅
- 后续 M3–M4：分步运行模式 / 长跑 / v1 冻结 — 见 `计划书.md`
