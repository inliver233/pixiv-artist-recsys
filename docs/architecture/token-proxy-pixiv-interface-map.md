# Token / Proxy / Pixiv Interface Map

## Goal
在真实 Pixiv 接入开始前，先明确未来模块边界与来源映射，避免后续实现把鉴权、代理、抓取、排序耦合到一起。

## Target modules
- `app/auth/*`（当前对应 `src/pixiv_artist_recsys/services` 的未来扩展方向）
- `app/proxy/*`
- `app/pixiv/*`
- `app/ingest/*`

## Source mapping

| Source repo | Source file | Future target | Planned responsibility |
|---|---|---|---|
| Random-image-api | `backend/app/pixiv/oauth.py` | `auth/token_service.py` | refresh token -> access token 刷新 |
| Random-image-api | `backend/app/pixiv/access_token_cache.py` | `auth/token_cache.py` | access token cache 与刷新边界 |
| Random-image-api | `backend/app/pixiv/token_strategy.py` | `auth/token_strategy.py` | 多 token 选择策略 |
| Random-image-api | `backend/app/core/proxy_routing.py` | `proxy/router.py` | 按 host/pool/token 选择代理 |
| Random-image-api | `backend/app/core/bindings_recompute.py` | `proxy/binding.py` | token-proxy 稳定绑定 |
| Random-image-api | `backend/app/core/failover.py` | `proxy/failover.py` | rate-limit / proxy error 分类与回退 |
| Random-image-api | `backend/app/jobs/handlers/hydrate_metadata.py` | `ingest/hydrator.py` | illust detail 元数据补水与持久化 |
| pixiv-downloader | `common/PixivAppApi.py` | `pixiv/app_api.py` | following / user detail / illust detail 封装 |
| pixiv-downloader | `PixivMultiRunner.py` | `ingest/runner.py` | 批量同步与调度思路 |
| pixiv-viewer | `src/api/client/pixiv-api.js` | `pixiv/endpoints.py` | 推荐用户/相关推荐/搜索端点清单 |
| Pixiv-XP-Pusher | `pixiv_client.py` | `pixiv/client_adapter.py` | 统一高层 Pixiv client 适配器 |

## Implementation order suggestion
1. `AUTH-001`：单 token refresh service
2. `AUTH-002`：access token cache
3. `PROXY-001`：proxy policy + binding state model
4. `PIXIV-001`：Pixiv App API endpoint wrapper
5. `INGEST-001`：following sync
6. `INGEST-002`：illust hydration

## Design guardrails
- token 服务不能直接知道排序逻辑
- proxy 服务不能持有业务状态，只维护路由/健康度
- pixiv client 只返回标准化 DTO，不直接写数据库
- ingest 服务负责把 Pixiv DTO 转为本地领域模型并入库
