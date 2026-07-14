# 实网自测清单（v0.2 本地可用）

在真实 refresh token 下逐项勾选。token **只**放本机环境变量或本地文件，**禁止**写入 git / issue / plan。

## 0. 准备

- [ ] 仓库干净可测：`python -m unittest` 全绿
- [ ] `python -m pixiv_artist_recsys init-db`
- [ ] `python -m pixiv_artist_recsys show-config` 路径符合预期
- [ ] （可选）配置 `PIXIV_ARTIST_RECSYS_PROXY_URLS` 后 `show-proxy-state`
- [ ] `$env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN = '...'`（本机 shell，勿提交；别名 `PIXIV_REFRESH_TOKEN` 亦可）
- [ ] （可选）`$env:PIXIV_ARTIST_RECSYS_PROXY_URLS = 'http://host:port,...'`

## 1. 鉴权与轮换

- [ ] `sync-following --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN` 成功
- [ ] 再次运行同一命令：若 Pixiv 已轮换 refresh，库内应有新 rotated；旧 CLI 值仍能刷新
- [ ] 故意传错误 refresh：错误信息含 status / body 摘要，而非裸 traceback 不明原因

## 2. 分步链路

- [ ] `hydrate-followed-illusts ... --max-artists 20 --no-sync-following`
- [ ] `build-profile --seed-user-id <id>` 出现合理 top_tags
- [ ] `build-candidates ... --max-seed-artists 20`
- [ ] `hydrate-candidate-illusts ... --max-artists 40`
- [ ] `recommend-from-store ... --max-results 20` 输出含 `user_id/score/reasons/top_illust_ids`

## 3. 一键与批处理

- [ ] `full-recommend` 日常档参数能跑完并写出 run
- [ ] `run-manifest` 使用**本机拷贝**的 daily 示例（已替换 seed/token）成功
- [ ] `list-runs` / `export-run` / `show-run-audit` 可查

## 4. 质量与反馈

- [ ] 结果中无已关注画师
- [ ] `allow_ai=false` / `allow_r18=false` 时结果符合预期
- [ ] `record-feedback --action dislike|block` 后再次 `recommend-from-store` 抑制对应 UID
- [ ] reasons 中可见 quality / multi-source 线索

## 5. 稳定性

- [ ] 人为限流或弱网：429/5xx 有退避重试或可理解错误
- [ ] 关注数 >100 时使用 `max-seed-artists` / `max-candidate-artists` 不会无界打 API
- [ ] 中断后可从分步命令续跑

## 6. 安全复查

- [ ] `git status` 无 `.env` / `*.sqlite3` / 含真 token 的 manifest
- [ ] 远程仓库历史无 token 字符串

全部勾选即可视为个人本地 **v0.2 可用**；未完成项记入 `docs/backlog.md`，不阻塞本版。
