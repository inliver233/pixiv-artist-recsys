# Backlog（不阻塞 v0.2）

来自 `计划书.md` P1 残留与 P2，按需挑做。

## 近期（质量 / 体验）

- [ ] Profile：默认停用词表、时间衰减、标签对权重调参
- [ ] 可选 ranking 端点作为召回源
- [ ] CLI 默认参数环境变量化（`followed_artist_limit` 等）
- [ ] 更细的 API 分步端点（与 CLI 完全对称）
- [ ] 失败 job 自动重试策略（manifest 级）

## 中期（安全 / 多账号）

- [ ] token 加密存储（当前 access 明文落库，仅本地可接受）
- [ ] 多账号 token 池与调度
- [ ] 代理绑定策略可视化 / 导出

## 远期（产品扩展）

- [ ] 简易调试 Web / 结果浏览
- [ ] embedding / 可选 LLM rerank
- [ ] 与 Random-image-api 对接：导出优质 UID 供图池
- [ ] 非标准库 HTTP 客户端（若 urllib 稳定性不够再评估 httpx）

## 明确非目标（v1）

- Web 完整前端
- 多账号 SaaS
- 原图下载站
- ML embedding 必选
