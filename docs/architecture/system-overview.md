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

## First implementation boundary
当前 repo 先实现 4 层骨架：
- 本地设置与项目目录管理
- 领域模型与 SQLite schema
- 服务接口与 recommendation orchestrator
- CLI dry-run / smoke tests

## Module map
- `src/pixiv_artist_recsys/config.py`: 配置与路径
- `src/pixiv_artist_recsys/domain/`: 核心实体和值对象
- `src/pixiv_artist_recsys/storage/`: SQLite schema / repository
- `src/pixiv_artist_recsys/services/`: auth/proxy/profile/candidate/rank 等端口
- `src/pixiv_artist_recsys/pipeline/`: recommendation pipeline
- `src/pixiv_artist_recsys/cli.py`: 本地命令入口

## Near-term roadmap
- Phase 1: dry-run skeleton
- Phase 2: token / pixiv client / following ingest 真实实现（当前进行中）
- Phase 3: followings ingest + artist profile
- Phase 4: candidate retrieval + ranking
- Phase 5: feedback loop + metrics
