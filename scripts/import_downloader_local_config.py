#!/usr/bin/env python3
"""Import mother/child tokens + proxy pool from pixiv-downloader-personal into local recsys config.

Writes ONLY gitignored paths:
  - .env
  - data/local/run_env.ps1
  - data/local/proxies.txt
  - data/local/import_summary.json (no full tokens)

Never prints full refresh tokens.
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_DOWNLOADER = Path(r'E:/pixiv-download-修改版本/pixiv-downloader-personal')
REPO_ROOT = Path(__file__).resolve().parents[1]


def mask_token(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return '(empty)'
    if len(value) < 12:
        return f'(len={len(value)})'
    return f'{value[:4]}...{value[-4:]} (len={len(value)})'


def mask_proxy(url: str) -> str:
    url = (url or '').strip()
    if not url:
        return ''
    return re.sub(r'(://)([^/@]+)@', r'\1***@', url)


def _env_escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def load_multi_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def pick_accounts(cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    accounts = list(cfg.get('accounts') or [])
    mother = next((a for a in accounts if a.get('follow_source') and (a.get('refresh_token') or '').strip()), None)
    if mother is None:
        mother = next((a for a in accounts if (a.get('id') or '') == 'mother' and (a.get('refresh_token') or '').strip()), None)
    children = [
        a
        for a in accounts
        if a.get('enabled') and (a.get('refresh_token') or '').strip() and not a.get('follow_source') and a is not mother
    ]
    child = children[0] if children else None
    return mother, child, children


def guess_seed_user_id(downloader_root: Path, mother: dict[str, Any] | None) -> int | None:
    candidates: list[str] = []
    if mother:
        cookie = str(mother.get('cookie') or '').strip()
        if cookie and '_' in cookie:
            candidates.append(cookie.split('_', 1)[0])
    ini = downloader_root / 'config.ini'
    if ini.exists():
        cp = configparser.ConfigParser()
        cp.read(ini, encoding='utf-8')
        if cp.has_section('Authentication'):
            cookie = str(cp.get('Authentication', 'cookie', fallback='') or '').strip()
            if cookie and '_' in cookie:
                candidates.append(cookie.split('_', 1)[0])
            for key in ('user_id', 'userid', 'pixiv_user_id'):
                if cp.has_option('Authentication', key):
                    candidates.append(str(cp.get('Authentication', key) or '').strip())
    for raw in candidates:
        if raw.isdigit():
            return int(raw)
    return None


def fetch_easy_proxies(easy: dict[str, Any], timeout: float = 15.0) -> list[str]:
    base = str(easy.get('base_url') or '').rstrip('/')
    if not base:
        return []
    password = str(easy.get('password') or '')
    headers: dict[str, str] = {'User-Agent': 'pixiv-artist-recsys-import/1.0'}
    if password:
        auth_req = urllib.request.Request(
            f'{base}/api/auth',
            data=json.dumps({'password': password}).encode('utf-8'),
            headers={**headers, 'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(auth_req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode('utf-8', errors='replace') or '{}')
        token = str(body.get('token') or '').strip()
        if token:
            headers['Authorization'] = f'Bearer {token}'
    export_req = urllib.request.Request(f'{base}/api/export', headers=headers, method='GET')
    with urllib.request.urlopen(export_req, timeout=timeout) as resp:
        text = resp.read().decode('utf-8', errors='replace')
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith('#')]
    return lines


def collect_proxies(cfg: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    meta: dict[str, Any] = {'static_count': 0, 'easy_count': 0, 'easy_error': ''}
    proxies: list[str] = []
    pp = cfg.get('proxy_pool') or {}
    static = [str(p).strip() for p in (pp.get('proxies') or []) if str(p).strip()]
    meta['static_count'] = len(static)
    proxies.extend(static)
    easy = pp.get('easy_proxies') or {}
    if easy:
        try:
            exported = fetch_easy_proxies(easy)
            meta['easy_count'] = len(exported)
            proxies.extend(exported)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            meta['easy_error'] = f'{type(exc).__name__}: {str(exc)[:160]}'
    # de-dupe preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for p in proxies:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique, meta


def write_env_file(
    path: Path,
    *,
    seed_user_id: int | None,
    mother_token: str,
    child_token: str,
    proxy_urls: str,
) -> None:
    lines = [
        '# Auto-generated by scripts/import_downloader_local_config.py — DO NOT COMMIT',
        '# This file is gitignored. Re-run the import script to refresh.',
        '',
        '# Ops / child token (hydrate, candidates, ranking API calls)',
        f'PIXIV_ARTIST_RECSYS_REFRESH_TOKEN={child_token}',
        f'PIXIV_REFRESH_TOKEN={child_token}',
        '',
        '# Mother token — following sync only',
        f'PIXIV_ARTIST_RECSYS_FOLLOWING_REFRESH_TOKEN={mother_token}',
        f'PIXIV_FOLLOWING_REFRESH_TOKEN={mother_token}',
        '',
    ]
    if seed_user_id is not None:
        lines.append(f'PIXIV_ARTIST_RECSYS_SEED_USER_ID={seed_user_id}')
        lines.append('')
    if proxy_urls:
        lines.append(f'PIXIV_ARTIST_RECSYS_PROXY_URLS={proxy_urls}')
        lines.append('PIXIV_ARTIST_RECSYS_PROXY_ALLOW_DIRECT=1')
        lines.append('')
    lines.extend(
        [
            'PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS=3',
            'PIXIV_ARTIST_RECSYS_HTTP_RETRY_BASE_DELAY_S=0.5',
            '',
        ]
    )
    path.write_text('\n'.join(lines), encoding='utf-8')


def write_ps1(
    path: Path,
    *,
    seed_user_id: int | None,
    mother_token: str,
    child_token: str,
    proxy_urls: str,
) -> None:
    lines = [
        '# Auto-generated — DO NOT COMMIT',
        '# Load into current PowerShell session:',
        '#   . .\\data\\local\\run_env.ps1',
        '',
        f'$env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN = {_ps_single_quote(child_token)}',
        f'$env:PIXIV_REFRESH_TOKEN = {_ps_single_quote(child_token)}',
        f'$env:PIXIV_ARTIST_RECSYS_FOLLOWING_REFRESH_TOKEN = {_ps_single_quote(mother_token)}',
        f'$env:PIXIV_FOLLOWING_REFRESH_TOKEN = {_ps_single_quote(mother_token)}',
    ]
    if seed_user_id is not None:
        lines.append(f"$env:PIXIV_ARTIST_RECSYS_SEED_USER_ID = '{seed_user_id}'")
    if proxy_urls:
        lines.append(f'$env:PIXIV_ARTIST_RECSYS_PROXY_URLS = {_ps_single_quote(proxy_urls)}')
        lines.append("$env:PIXIV_ARTIST_RECSYS_PROXY_ALLOW_DIRECT = '1'")
    seed_display = str(seed_user_id) if seed_user_id is not None else ''
    lines.extend(
        [
            "$env:PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS = '3'",
            "$env:PIXIV_ARTIST_RECSYS_HTTP_RETRY_BASE_DELAY_S = '0.5'",
            "$env:PYTHONPATH = 'src'",
            '',
            'Write-Host "Loaded mother/child tokens + proxy pool into env (tokens masked in summary only)."',
            f'Write-Host "SEED_USER_ID={seed_display}"',
            '',
        ]
    )
    path.write_text('\n'.join(lines), encoding='utf-8')


def write_runbook(path: Path, *, seed_user_id: int | None) -> None:
    sid = str(seed_user_id) if seed_user_id is not None else '<SEED_USER_ID>'
    content = f"""# 本机快速运行（母号只同步关注 / 子号做其余操作）

配置由 `scripts/import_downloader_local_config.py` 从 downloader 导入。
**不要**把 `.env`、`data/local/*`、sqlite 提交到 git。

## 1. 加载环境

```powershell
cd {REPO_ROOT}
. .\\data\\local\\run_env.ps1
python -m pixiv_artist_recsys init-db
python -m pixiv_artist_recsys show-proxy-state
```

## 2. 推荐：分步（母号只跑第 1 步）

```powershell
# 母号：仅同步关注（优先 FOLLOWING_REFRESH_TOKEN）
python -m pixiv_artist_recsys sync-following --seed-user-id {sid}

# 子号：后续操作（用 REFRESH_TOKEN / 默认 --refresh-token 环境）
python -m pixiv_artist_recsys hydrate-followed-illusts --seed-user-id {sid} --no-sync-following --per-artist-limit 8 --max-artists 40
python -m pixiv_artist_recsys build-profile --seed-user-id {sid}
python -m pixiv_artist_recsys build-candidates --seed-user-id {sid} --max-seed-artists 40
python -m pixiv_artist_recsys hydrate-candidate-illusts --seed-user-id {sid} --per-artist-limit 5 --max-artists 80
python -m pixiv_artist_recsys recommend-from-store --seed-user-id {sid} --max-results 50
```

## 3. 一键 full-recommend（母+子）

`full-recommend` 会在同一次运行里：母号 token 只用于 following sync，子号 token 用于 hydrate/candidates。

```powershell
python -m pixiv_artist_recsys full-recommend --seed-user-id {sid} --max-seed-artists 40 --max-candidate-artists 80
```

若 shell 未加载 env，可显式传：

```powershell
python -m pixiv_artist_recsys full-recommend `
  --seed-user-id {sid} `
  --refresh-token $env:PIXIV_ARTIST_RECSYS_REFRESH_TOKEN `
  --following-refresh-token $env:PIXIV_ARTIST_RECSYS_FOLLOWING_REFRESH_TOKEN
```

## 4. 安全

- 真实 token 只在本机 `.env` / `data/local/run_env.ps1`
- 关注列表很大时务必保留 `max-seed-artists` / `max-candidate-artists` 上限
"""
    path.write_text(content, encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Import local recsys config from pixiv-downloader-personal')
    parser.add_argument('--downloader-root', type=Path, default=DEFAULT_DOWNLOADER)
    parser.add_argument('--child-id', default='', help='Prefer this child account id (default: first enabled child)')
    parser.add_argument('--seed-user-id', type=int, default=0, help='Override guessed mother seed user id')
    parser.add_argument('--skip-easy-proxies', action='store_true')
    parser.add_argument('--repo-root', type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    downloader_root = args.downloader_root
    multi_path = downloader_root / 'multi_config.json'
    if not multi_path.exists():
        print(f'ERROR: multi_config.json not found: {multi_path}', file=sys.stderr)
        return 1

    cfg = load_multi_config(multi_path)
    mother, child, children = pick_accounts(cfg)
    if args.child_id:
        child = next((a for a in children if str(a.get('id')) == args.child_id), child)
    if mother is None or not (mother.get('refresh_token') or '').strip():
        print('ERROR: mother account with refresh_token not found', file=sys.stderr)
        return 1
    if child is None or not (child.get('refresh_token') or '').strip():
        print('ERROR: enabled child account with refresh_token not found', file=sys.stderr)
        return 1

    mother_token = str(mother['refresh_token']).strip()
    child_token = str(child['refresh_token']).strip()
    seed_user_id = args.seed_user_id or guess_seed_user_id(downloader_root, mother)

    if args.skip_easy_proxies:
        static = [str(p).strip() for p in ((cfg.get('proxy_pool') or {}).get('proxies') or []) if str(p).strip()]
        proxies, proxy_meta = static, {'static_count': len(static), 'easy_count': 0, 'easy_error': 'skipped'}
    else:
        proxies, proxy_meta = collect_proxies(cfg)

    proxy_urls = ','.join(proxies)

    local_dir = args.repo_root / 'data' / 'local'
    local_dir.mkdir(parents=True, exist_ok=True)
    env_path = args.repo_root / '.env'
    ps1_path = local_dir / 'run_env.ps1'
    proxies_path = local_dir / 'proxies.txt'
    summary_path = local_dir / 'import_summary.json'
    runbook_path = local_dir / 'HOW_TO_RUN.md'

    write_env_file(
        env_path,
        seed_user_id=seed_user_id,
        mother_token=mother_token,
        child_token=child_token,
        proxy_urls=proxy_urls,
    )
    write_ps1(
        ps1_path,
        seed_user_id=seed_user_id,
        mother_token=mother_token,
        child_token=child_token,
        proxy_urls=proxy_urls,
    )
    proxies_path.write_text('\n'.join(proxies) + ('\n' if proxies else ''), encoding='utf-8')
    write_runbook(runbook_path, seed_user_id=seed_user_id)

    summary = {
        'downloader_root': str(downloader_root),
        'mother_account_id': mother.get('id'),
        'child_account_id': child.get('id'),
        'mother_token': mask_token(mother_token),
        'child_token': mask_token(child_token),
        'seed_user_id': seed_user_id,
        'proxy_count': len(proxies),
        'proxy_meta': proxy_meta,
        'proxy_samples': [mask_proxy(p) for p in proxies[:3]],
        'wrote': {
            'env': str(env_path),
            'run_env_ps1': str(ps1_path),
            'proxies_txt': str(proxies_path),
            'runbook': str(runbook_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if seed_user_id is None:
        print('WARNING: seed_user_id not guessed; set PIXIV_ARTIST_RECSYS_SEED_USER_ID or pass --seed-user-id', file=sys.stderr)
    if proxy_meta.get('easy_error'):
        print(f"NOTE: easy_proxies: {proxy_meta['easy_error']}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
