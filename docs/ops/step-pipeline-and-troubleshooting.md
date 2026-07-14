# 分步运行与常见故障

个人本地长跑推荐时，优先用**分步命令**而不是一上来 `full-recommend`：任何一步失败后，可从中断附近重跑，不必重做全部 API。

## 1. 推荐分步顺序

```text
sync-following
  → hydrate-followed-illusts --no-sync-following
  → build-profile
  → build-candidates
  → hydrate-candidate-illusts
  → recommend-from-store
```

一键路径仍可用：`full-recommend` / `run-manifest`（内部是同一 live pipeline）。

## 2. 命令速查（PowerShell）

把 `<id>` / `$env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN` 换成本地值。**不要**把真实 token 写进仓库或 issue。  
（别名 `PIXIV_REFRESH_TOKEN` 也被 runtime 接受；`.env` 文件不会自动加载，需 export 或传 CLI。）

```powershell
# 1) 只同步关注
python -m pixiv_artist_recsys sync-following `
  --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN

# 2) 补关注画师代表作（可跳过再同步）
python -m pixiv_artist_recsys hydrate-followed-illusts `
  --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN `
  --per-artist-limit 8 --max-artists 40 --no-sync-following

# 3) 本地画像（纯库内）
python -m pixiv_artist_recsys build-profile --seed-user-id <id>

# 4) 多源候选召回
python -m pixiv_artist_recsys build-candidates `
  --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN `
  --max-seed-artists 40

# 5) 候选作品 hydrate
python -m pixiv_artist_recsys hydrate-candidate-illusts `
  --seed-user-id <id> --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN `
  --per-artist-limit 5 --max-artists 80

# 6) 纯离线排序
python -m pixiv_artist_recsys recommend-from-store `
  --seed-user-id <id> --max-results 50 --min-bookmarks 30
```

说明：

| 命令 | 是否打 Pixiv | 依赖库内数据 |
|------|:------------:|--------------|
| `sync-following` | 是 | token |
| `hydrate-followed-illusts` | 是（可选再 sync） | following edges |
| `build-profile` | 否 | followed illusts + tags |
| `build-candidates` | 是 | following + 可选 illust seeds |
| `hydrate-candidate-illusts` | 是 | artist_candidates |
| `recommend-from-store` | 否 | candidates + candidate illusts + profile |

## 3. Job Manifest 与定时思路

示例文件：

- `examples/manifest-daily.json` — 日常推荐档
- `examples/manifest-deep.json` — 深度扫描档

运行：

```powershell
# 先把 manifest 里的 seed_user_id / refresh_token 改成本地值（仅本机文件）
python -m pixiv_artist_recsys run-manifest `
  --manifest examples/manifest-daily.json `
  --output-dir data/exports
```

定时（本机，任选其一）：

- **Windows 任务计划程序**：每天离峰跑 `run-manifest`，工作目录设为仓库根，环境变量里放 `PIXIV_REFRESH_TOKEN`（不要写进任务 XML 明文仓库）。
- **cron / systemd timer**（WSL 或 Linux）：`0 3 * * * cd /path && python -m pixiv_artist_recsys run-manifest --manifest ...`

项目**不内置** cron 守护进程；manifest 是可重复的批处理入口，调度由系统负责。

失败策略：

- 默认继续后续 job，结果里 `jobs_failed` / `errors` 可查
- `--fail-fast` 遇错即停

## 4. 代理绑定

环境变量（见 `.env.example`）：

| 变量 | 作用 |
|------|------|
| `PIXIV_ARTIST_RECSYS_PROXY_URLS` | 逗号分隔代理列表 |
| `PIXIV_ARTIST_RECSYS_PROXY_MAX_FAILURES` | 连续失败次数后冷却 |
| `PIXIV_ARTIST_RECSYS_PROXY_COOLDOWN_SECONDS` | 冷却秒数 |
| `PIXIV_ARTIST_RECSYS_PROXY_ALLOW_DIRECT` | 代理全挂时是否允许直连（默认允许） |
| `PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS` | 单请求最大尝试（含首次） |
| `PIXIV_ARTIST_RECSYS_HTTP_RETRY_BASE_DELAY_S` | 429/5xx 退避基数 |

检查当前代理状态：

```powershell
python -m pixiv_artist_recsys show-proxy-state
```

绑定原则：

- 同一 seed 的 token 尽量走稳定代理，避免频繁换 IP 触发风控
- 代理失败会 failover；冷却后可再试
- 本地调试可清空 `PROXY_URLS` 走直连

## 5. 常见故障表

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| OAuth 401 / invalid_grant | refresh 已轮换或作废；CLI 仍传旧 token 且库内无 rotated | 用最新 refresh；确认上次成功刷新后 SQLite 有 `refresh_token_rotated`；删库 token 行后重登 |
| App API 401 | access 过期且刷新失败 | 同上；检查系统时间；看错误 body 摘要 |
| 429 rate limit | 请求过密 / 无界相关 | 降低 `max-seed-artists` / `max-candidate-artists`；依赖内置 retry；分步跑并间隔 |
| 连接超时 / proxy error | 代理不可用 | `show-proxy-state`；换代理或允许 direct fallback |
| `recommend-from-store` 空结果 | 未 build candidates / 未 hydrate / 门槛过高 | 先分步补数据；调低 `min-bookmarks` / `min-score`；确认 profile 有标签 |
| hydrate 很慢 | 关注/候选过多 | `--max-artists` 收紧；分多天补 hydrate |
| 结果全是「神图作者」噪声 | 画像过薄 / 单相关源 | 提高 followed hydrate；打开 multi-source；看 reasons 里 median/consistency |
| Windows 路径 / 编码异常 | 工作目录不对 | 在仓库根执行；`PIXIV_ARTIST_RECSYS_DATA_DIR` 指向可写路径 |
| 测试 0 条 / import 失败 | `PYTHONPATH` 未含 `src` | ` $env:PYTHONPATH='src'; python -m unittest` |

## 6. 安全提醒

- 真实 refresh token、`.env`、sqlite **不得**提交 git
- manifest 示例里的 token 占位符务必本机替换，勿 push 真值
- 详见 `AGENTS.md` / `.env.example`
