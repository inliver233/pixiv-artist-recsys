# System Overview

## Product goal
输入 Pixiv refresh token 与用户偏好，输出符合已关注审美、尚未关注、质量足够高的画师 UID 列表。

## Core pipeline
1. Auth: refresh token / access token 管理
2. Ingest: 获取当前用户关注画师与代表作品
3. Profile: 构建用户审美画像（tags / tag pairs / artist clusters / negative profile）
4. Candidate: 多召回源获取候选画师
5. Hydrate: 拉取候选画师与作品详情
6. Rank: artist-level quality + taste match + novelty + diversity
7. Feedback: 记录 follow / dislike / block 回流画像

## Implemented baseline
当前 repo 已实现：
- OAuth refresh / token cache / token coordinator
- Pixiv App API client（following / user detail / user illusts / illust detail / user related / illust related）
- following sync、followed-artist hydration、taste profile、candidate retrieval、heuristic rank
- CLI：`init-db` / `show-config` / `dry-run-recommend` / `hydrate-followed-illusts` / `build-profile` / `recommend-from-store`

## Current implementation focus
当前推进到第 4 批：
- 把以上分步能力串成 live recommendation pipeline
- 增加 candidate artist hydration
- 输出一次执行即可获得 artist uid 列表的 `full-recommend` CLI 闭环

## Module map
- `src/pixiv_artist_recsys/config.py`: 配置与路径
- `src/pixiv_artist_recsys/domain/`: 核心实体和值对象
- `src/pixiv_artist_recsys/storage/`: SQLite schema / repository
- `src/pixiv_artist_recsys/services/`: 早期 dry-run ports / stubs
- `src/pixiv_artist_recsys/auth/`: OAuth refresh / token cache / coordinator
- `src/pixiv_artist_recsys/pixiv/`: Pixiv App API client / DTO
- `src/pixiv_artist_recsys/ingest/`: following / hydration
- `src/pixiv_artist_recsys/profile/`: taste profile
- `src/pixiv_artist_recsys/candidate/`: related-based retrieval
- `src/pixiv_artist_recsys/rank/`: heuristic artist rank
- `src/pixiv_artist_recsys/pipeline/`: dry-run pipeline + upcoming live orchestration
- `src/pixiv_artist_recsys/cli.py`: 本地命令入口

## Near-term roadmap
- Phase 1: dry-run skeleton ✅
- Phase 2: token / pixiv client / following ingest ✅
- Phase 3: followings ingest + artist profile ✅
- Phase 4: candidate retrieval + ranking ✅
- Phase 5: full live pipeline（当前进行中）
- Phase 6: proxy/failover + feedback loop
