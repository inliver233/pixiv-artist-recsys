# Issue Map

## Current batch
- `BOOT-001`: 仓库工作流与本地 Git 基线
- `DOCS-001`: 调查矩阵与系统蓝图
- `CORE-001`: Python 项目骨架与配置模型
- `CORE-002`: 本地 SQLite 存储与领域模型
- `CORE-003`: 推荐流程接口与服务编排骨架
- `APP-001`: CLI 与运行目录初始化
- `TEST-001`: smoke tests
- `OPS-001`: token/proxy/pixiv client 接口映射

## Suggested next batches after current milestone
1. `AUTH-*`: refresh token / access token / token health
2. `PROXY-*`: proxy pools / binding / failover
3. `PIXIV-*`: Pixiv App API client wrapper
4. `INGEST-*`: following sync / illust hydration
5. `PROFILE-*`: taste profiler / negative profile / embeddings
6. `CAND-*`: related users / related works / search recall
7. `RANK-*`: artist quality scoring / diversity / explanation
8. `FEED-*`: feedback loop / recommendation audit trail

## Batch 2
- `DOCS-002`: 第二批 auth/client/ingest 计划与 issue 资产
- `AUTH-001`: OAuth refresh service 与 token persistence
- `AUTH-002`: access token cache
- `PIXIV-001`: Pixiv App API client 与 DTO
- `INGEST-001`: following sync service
- `TEST-002`: batch regression

## Batch 3
- `DOCS-003`: 第三批 profile/candidate/rank 计划资产
- `INGEST-002`: followed-artist illust hydration + tags
- `PROFILE-001`: taste profile build
- `CAND-001`: related-user / related-illust candidate retrieval
- `RANK-001`: heuristic artist ranking
- `APP-002`: CLI 扩展
- `TEST-003`: batch regression

## Batch 4
- `DOCS-004`: 第四批 live-pipeline 计划资产
- `INGEST-003`: candidate artist hydration
- `PIPE-001`: live recommendation pipeline
- `APP-003`: CLI full-recommend
- `TEST-004`: batch regression

## Batch 5
- `DOCS-005`: 第五批 quality-guardrails 计划资产
- `CORE-004`: seed user 偏好持久化
- `RANK-002`: quality / AI / R18 guardrails
- `APP-004`: CLI 过滤参数
- `TEST-005`: batch regression

## Batch 6
- `DOCS-006`: 第六批 proxy/failover 计划资产
- `PROXY-001`: proxy pool + failover transport
- `APP-005`: CLI proxy state / integration
- `TEST-006`: batch regression
