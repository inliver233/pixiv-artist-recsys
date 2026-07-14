#!/usr/bin/env python3
"""Local launcher: status check + one-click run for pixiv-artist-recsys.

Usage:
  python start.py                 # interactive menu
  python start.py status          # print status only
  python start.py run             # one-click full pipeline (daily-large preset)
  python start.py run --preset deep
  python start.py steps           # step pipeline (mother once, then child ops)
  python start.py import-config   # re-import from downloader-personal

Secrets stay in .env / data/local (gitignored). Tokens are never printed in full.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DOWNLOADER = Path(r'E:/pixiv-download-修改版本/pixiv-downloader-personal')
SRC = REPO_ROOT / 'src'

# ~2600 following: seed/candidate caps avoid unbounded API; following sync itself still full-syncs.
PRESETS: dict[str, dict[str, Any]] = {
    'quick': {
        'label': '日常快速（少 API）',
        'followed_artist_limit': 5,
        'candidate_artist_limit': 3,
        'max_related_per_artist': 4,
        'max_related_per_illust': 4,
        'max_seed_artists': 30,
        'max_candidate_artists': 50,
        'max_user_recommended': 20,
        'max_tag_search_tags': 3,
        'max_tag_search_illusts': 12,
        'max_results': 30,
        'min_bookmarks': 30,
        'min_score': 0.5,
        'diversity_per_tag': 2,
    },
    'daily': {
        'label': '日常推荐（约 2600 关注默认）',
        'followed_artist_limit': 8,
        'candidate_artist_limit': 5,
        'max_related_per_artist': 5,
        'max_related_per_illust': 5,
        'max_seed_artists': 60,
        'max_candidate_artists': 100,
        'max_user_recommended': 30,
        'max_tag_search_tags': 5,
        'max_tag_search_illusts': 20,
        'max_results': 50,
        'min_bookmarks': 30,
        'min_score': 0.5,
        'diversity_per_tag': 2,
    },
    'deep': {
        'label': '深度扫描（更慢、更多召回）',
        'followed_artist_limit': 12,
        'candidate_artist_limit': 8,
        'max_related_per_artist': 8,
        'max_related_per_illust': 8,
        'max_seed_artists': 120,
        'max_candidate_artists': 180,
        'max_user_recommended': 40,
        'max_tag_search_tags': 8,
        'max_tag_search_illusts': 30,
        'max_results': 80,
        'min_bookmarks': 20,
        'min_score': 0.4,
        'diversity_per_tag': 3,
    },
}


def ensure_sys_path() -> None:
    src = str(SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def mask_token(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return '(empty)'
    if len(value) < 12:
        return f'(len={len(value)})'
    return f'{value[:4]}...{value[-4:]} (len={len(value)})'


def mask_proxy_url(url: str) -> str:
    import re

    url = (url or '').strip()
    if not url:
        return ''
    masked = re.sub(r'(://)([^/@]+)@', r'\1***@', url)
    if len(masked) > 64:
        return masked[:64] + '...'
    return masked


def _proxy_samples(proxies: list[Any]) -> list[str]:
    samples: list[str] = []
    for item in proxies[:3]:
        if isinstance(item, dict):
            url = str(item.get('proxy_url') or item.get('url') or '')
        else:
            url = str(item)
        samples.append(mask_proxy_url(url))
    return samples


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env loader (no export of values to stdout)."""
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        # Do not override already-exported shell values.
        if key not in os.environ or not str(os.environ.get(key, '')).strip():
            os.environ[key] = value
        loaded[key] = value
    return loaded


def _env_get(*keys: str, env: Mapping[str, str] | None = None) -> str:
    env = env or os.environ
    for key in keys:
        value = str(env.get(key, '') or '').strip()
        if value:
            return value
    return ''


def resolve_seed_user_id(cli_value: int | None = None) -> int | None:
    if cli_value and cli_value > 0:
        return int(cli_value)
    raw = _env_get('PIXIV_ARTIST_RECSYS_SEED_USER_ID', 'PIXIV_SEED_USER_ID')
    if raw.isdigit():
        return int(raw)
    return None


@dataclass(slots=True)
class StatusReport:
    payload: dict[str, Any]

    def print_human(self) -> None:
        p = self.payload
        print('=' * 60)
        print('pixiv-artist-recsys 状态')
        print('=' * 60)
        print(f"repo: {p['repo_root']}")
        print(f"env_file: {p['env_file']['path']}  exists={p['env_file']['exists']}  loaded_keys={p['env_file']['loaded_key_count']}")
        print()
        print('[Tokens]')
        t = p['tokens']
        print(f"  child/ops refresh : {t['child_refresh']['status']}  {t['child_refresh']['masked']}")
        print(f"  mother following  : {t['mother_refresh']['status']}  {t['mother_refresh']['masked']}")
        print(f"  access token      : {t['access']['status']}  {t['access']['masked']}")
        print(f"  dual-token mode   : {t['dual_token_mode']}")
        print(f"  seed_user_id      : {t['seed_user_id']}")
        print()
        print('[Downloader multi_config]')
        d = p['downloader']
        if not d['found']:
            print(f"  not found: {d['path']}")
        else:
            print(f"  path: {d['path']}")
            print(f"  accounts total={d['accounts_total']}  mother={d['mother_count']}  children_enabled={d['children_enabled']}  children_total={d['children_total']}")
            print(f"  mother_id={d['mother_id']}  first_child_id={d['first_child_id']}")
        print()
        print('[Proxy]')
        px = p['proxy']
        print(f"  enabled={px['enabled']}  count={px['count']}  allow_direct={px['allow_direct_fallback']}")
        if px['samples']:
            print(f"  samples: {', '.join(px['samples'][:3])}")
        print()
        print('[Database]')
        db = p['database']
        print(f"  path={db['path']}")
        print(f"  exists={db['exists']}  size_bytes={db['size_bytes']}")
        if db.get('error'):
            print(f"  error={db['error']}")
        else:
            print(
                f"  following_edges={db['following_edges']}  artists={db['artists']}  "
                f"illusts={db['illusts']}  candidates={db['candidates']}  "
                f"profile_tags={db['profile_tags']}  runs={db['runs']}  tokens={db['token_rows']}"
            )
            if db.get('latest_run'):
                print(f"  latest_run={db['latest_run']}")
        print()
        print('[Readiness]')
        r = p['readiness']
        for item in r['checks']:
            mark = 'OK' if item['ok'] else '!!'
            print(f"  [{mark}] {item['name']}: {item['detail']}")
        print(f"  ready_to_run={r['ready']}")
        if r['warnings']:
            print('  warnings:')
            for w in r['warnings']:
                print(f"    - {w}")
        print('=' * 60)


def inspect_downloader(path: Path) -> dict[str, Any]:
    multi = path / 'multi_config.json'
    out: dict[str, Any] = {
        'path': str(path),
        'found': multi.exists(),
        'accounts_total': 0,
        'mother_count': 0,
        'children_total': 0,
        'children_enabled': 0,
        'mother_id': None,
        'first_child_id': None,
    }
    if not multi.exists():
        return out
    try:
        cfg = json.loads(multi.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        out['error'] = f'{type(exc).__name__}: {exc}'
        return out
    accounts = list(cfg.get('accounts') or [])
    out['accounts_total'] = len(accounts)
    mothers = [a for a in accounts if a.get('follow_source') and str(a.get('refresh_token') or '').strip()]
    children = [a for a in accounts if not a.get('follow_source') and str(a.get('refresh_token') or '').strip()]
    out['mother_count'] = len(mothers)
    out['children_total'] = len(children)
    out['children_enabled'] = sum(1 for a in children if a.get('enabled'))
    out['mother_id'] = (mothers[0].get('id') if mothers else None)
    enabled_children = [a for a in children if a.get('enabled')]
    out['first_child_id'] = (enabled_children[0].get('id') if enabled_children else (children[0].get('id') if children else None))
    return out


def inspect_database(db_path: Path, seed_user_id: int | None) -> dict[str, Any]:
    info: dict[str, Any] = {
        'path': str(db_path),
        'exists': db_path.exists(),
        'size_bytes': db_path.stat().st_size if db_path.exists() else 0,
        'following_edges': 0,
        'artists': 0,
        'illusts': 0,
        'candidates': 0,
        'profile_tags': 0,
        'runs': 0,
        'token_rows': 0,
        'latest_run': None,
        'error': '',
    }
    if not db_path.exists():
        return info
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()

            def count(table: str, where: str = '', params: tuple[Any, ...] = ()) -> int:
                try:
                    sql = f'SELECT COUNT(*) FROM {table}'
                    if where:
                        sql += f' WHERE {where}'
                    row = cur.execute(sql, params).fetchone()
                    return int(row[0] if row else 0)
                except sqlite3.Error:
                    return 0

            if seed_user_id is not None:
                info['following_edges'] = count('seed_user_following_artists', 'seed_user_id = ?', (seed_user_id,))
                info['candidates'] = count('artist_candidates', 'seed_user_id = ?', (seed_user_id,))
                info['profile_tags'] = count('user_taste_profile', 'seed_user_id = ?', (seed_user_id,))
            else:
                info['following_edges'] = count('seed_user_following_artists')
                info['candidates'] = count('artist_candidates')
                info['profile_tags'] = count('user_taste_profile')
            info['artists'] = count('artists')
            info['illusts'] = count('illusts')
            info['runs'] = count('recommendation_runs')
            info['token_rows'] = count('pixiv_tokens')
            try:
                row = cur.execute(
                    'SELECT run_id, seed_user_id, mode, created_at FROM recommendation_runs ORDER BY created_at DESC LIMIT 1'
                ).fetchone()
                if row:
                    info['latest_run'] = {
                        'run_id': row[0],
                        'seed_user_id': row[1],
                        'mode': row[2],
                        'created_at': row[3],
                    }
            except sqlite3.Error:
                pass
        finally:
            conn.close()
    except sqlite3.Error as exc:
        info['error'] = f'{type(exc).__name__}: {exc}'
    return info


def build_status(*, downloader_root: Path, seed_user_id: int | None = None) -> StatusReport:
    ensure_sys_path()
    env_path = REPO_ROOT / '.env'
    loaded = load_dotenv(env_path)

    from pixiv_artist_recsys.config import load_settings
    from pixiv_artist_recsys.runtime import AppRuntime

    seed = resolve_seed_user_id(seed_user_id)
    child = AppRuntime.resolve_refresh_token()
    mother = AppRuntime.resolve_following_refresh_token()
    access = AppRuntime.resolve_access_token()

    settings = load_settings()
    settings.ensure_directories()
    runtime = AppRuntime.create()
    # initialize schema if missing so status is meaningful
    runtime.prepare()
    proxy_payload = runtime.proxy_state_payload()
    proxy_urls_raw = _env_get('PIXIV_ARTIST_RECSYS_PROXY_URLS')
    proxy_count_env = len([p for p in proxy_urls_raw.split(',') if p.strip()]) if proxy_urls_raw else 0

    db = inspect_database(settings.storage.sqlite_path, seed)
    downloader = inspect_downloader(downloader_root)

    checks: list[dict[str, Any]] = []
    warnings: list[str] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({'name': name, 'ok': ok, 'detail': detail})

    add_check('child_or_ops_token', bool(child or access), '子号 refresh 或 access 已配置' if (child or access) else '缺少 PIXIV_ARTIST_RECSYS_REFRESH_TOKEN')
    add_check(
        'mother_following_token',
        bool(mother) or bool(child or access),
        '母号 FOLLOWING token 已配置' if mother else '未配置母号（将用子号/ops token 同步关注）',
    )
    add_check('seed_user_id', seed is not None, str(seed) if seed is not None else '缺少 PIXIV_ARTIST_RECSYS_SEED_USER_ID')
    add_check('proxy_pool', proxy_payload['enabled'] or proxy_count_env > 0, f"enabled={proxy_payload['enabled']} count≈{max(len(proxy_payload.get('proxies') or []), proxy_count_env)}")
    add_check('database', True, str(settings.storage.sqlite_path))

    if seed is not None and db['following_edges'] == 0:
        warnings.append('本地关注边为 0：首次运行会用母号完整同步关注（~2600 可能较久）')
    if db['following_edges'] >= 1500:
        warnings.append(f"本地已有关注边 {db['following_edges']}：一键 run 默认只对其中 max-seed-artists 抽样 hydrate/召回，避免 API 爆炸")
    if mother and child and mother == child:
        warnings.append('母号与子号 refresh 相同，失去风控隔离意义')
    if not mother:
        warnings.append('建议配置 PIXIV_ARTIST_RECSYS_FOLLOWING_REFRESH_TOKEN（母号只做关注同步）')
    if not proxy_payload['enabled'] and proxy_count_env == 0:
        warnings.append('未配置代理池，将直连 Pixiv（可能不稳定）')

    ready = bool((child or access) and seed is not None)

    payload = {
        'repo_root': str(REPO_ROOT),
        'env_file': {
            'path': str(env_path),
            'exists': env_path.exists(),
            'loaded_key_count': len(loaded),
        },
        'tokens': {
            'child_refresh': {
                'status': 'set' if child else 'missing',
                'masked': mask_token(child),
            },
            'mother_refresh': {
                'status': 'set' if mother else 'missing',
                'masked': mask_token(mother),
            },
            'access': {
                'status': 'set' if access else 'missing',
                'masked': mask_token(access),
            },
            'dual_token_mode': bool(mother and (child or access) and mother != child),
            'seed_user_id': seed,
        },
        'downloader': downloader,
        'proxy': {
            'enabled': bool(proxy_payload.get('enabled')),
            'count': len(proxy_payload.get('proxies') or []) or proxy_count_env,
            'allow_direct_fallback': proxy_payload.get('allow_direct_fallback', True),
            'samples': _proxy_samples(proxy_payload.get('proxies') or []),
        },
        'database': db,
        'readiness': {
            'ready': ready,
            'checks': checks,
            'warnings': warnings,
        },
        'presets': {name: {'label': cfg['label'], 'max_seed_artists': cfg['max_seed_artists'], 'max_candidate_artists': cfg['max_candidate_artists']} for name, cfg in PRESETS.items()},
    }
    return StatusReport(payload=payload)


def _build_facade():
    ensure_sys_path()
    load_dotenv(REPO_ROOT / '.env')
    from pixiv_artist_recsys.application import ApplicationFacade
    from pixiv_artist_recsys.config import load_settings
    from pixiv_artist_recsys.runtime import AppRuntime

    runtime = AppRuntime.create(settings=load_settings())
    runtime.prepare()
    return ApplicationFacade(runtime=runtime)


def cmd_status(args: argparse.Namespace) -> int:
    report = build_status(downloader_root=Path(args.downloader_root), seed_user_id=args.seed_user_id)
    if args.json:
        print(json.dumps(report.payload, ensure_ascii=False, indent=2))
    else:
        report.print_human()
    return 0 if report.payload['readiness']['ready'] else 2


def cmd_import_config(args: argparse.Namespace) -> int:
    ensure_sys_path()
    script = REPO_ROOT / 'scripts' / 'import_downloader_local_config.py'
    if not script.exists():
        print(f'import script missing: {script}', file=sys.stderr)
        return 1
    # run as library-ish via subprocess-free import
    import importlib.util

    spec = importlib.util.spec_from_file_location('import_downloader_local_config', script)
    if spec is None or spec.loader is None:
        print('failed to load import script', file=sys.stderr)
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = ['--downloader-root', str(args.downloader_root), '--repo-root', str(REPO_ROOT)]
    if args.child_id:
        argv.extend(['--child-id', args.child_id])
    if args.seed_user_id:
        argv.extend(['--seed-user-id', str(args.seed_user_id)])
    return int(mod.main(argv))


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / '.env')
    report = build_status(downloader_root=Path(args.downloader_root), seed_user_id=args.seed_user_id)
    if not args.json:
        report.print_human()
    if not report.payload['readiness']['ready'] and not args.force:
        print('未就绪：请先配置 .env（或 python start.py import-config），再重试。可用 --force 强行继续。', file=sys.stderr)
        return 2

    seed = resolve_seed_user_id(args.seed_user_id)
    if seed is None:
        print('缺少 seed_user_id', file=sys.stderr)
        return 2

    preset_name = args.preset
    preset = dict(PRESETS[preset_name])
    # CLI overrides
    for key in (
        'max_seed_artists',
        'max_candidate_artists',
        'followed_artist_limit',
        'candidate_artist_limit',
        'max_results',
        'min_bookmarks',
    ):
        cli_key = key
        value = getattr(args, cli_key, None)
        if value is not None:
            preset[key] = value

    print()
    print(f">>> 一键启动 full-recommend  preset={preset_name} ({preset['label']})")
    print(
        f"    seed={seed} max_seed_artists={preset['max_seed_artists']} "
        f"max_candidate_artists={preset['max_candidate_artists']} max_results={preset['max_results']}"
    )
    print('    母号 token 仅用于 following sync；子号用于其余 API。关注全量同步可能较久。')
    print()

    facade = _build_facade()
    try:
        payload = facade.full_recommend_payload(
            seed_user_id=seed,
            refresh_token=None,  # from env
            following_refresh_token=None,  # from env
            followed_artist_limit=int(preset['followed_artist_limit']),
            candidate_artist_limit=int(preset['candidate_artist_limit']),
            max_related_per_artist=int(preset['max_related_per_artist']),
            max_related_per_illust=int(preset['max_related_per_illust']),
            max_seed_artists=int(preset['max_seed_artists']),
            max_candidate_artists=int(preset['max_candidate_artists']),
            max_user_recommended=int(preset['max_user_recommended']),
            max_tag_search_tags=int(preset['max_tag_search_tags']),
            max_tag_search_illusts=int(preset['max_tag_search_illusts']),
            max_results=int(preset['max_results']),
            min_bookmarks=int(preset['min_bookmarks']),
            min_score=float(preset['min_score']),
            diversity_per_tag=int(preset['diversity_per_tag']),
        )
    except Exception as exc:  # noqa: BLE001 — surface live failures cleanly
        print(f'RUN FAILED: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1

    out_dir = REPO_ROOT / 'data' / 'local' / 'exports'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"full-{payload.get('run_id', 'unknown')}.json"
    # strip nothing sensitive — payload should only have masked token_refs
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    summary = {
        'run_id': payload.get('run_id'),
        'seed_user_id': payload.get('seed_user_id'),
        'recommended_count': len(payload.get('recommended_artist_ids') or []),
        'recommended_artist_ids': payload.get('recommended_artist_ids'),
        'token_roles': payload.get('token_roles'),
        'stats': payload.get('stats'),
        'output_path': str(out_path),
        'preset': preset_name,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"完整结果已写入: {out_path}")
    return 0


def cmd_steps(args: argparse.Namespace) -> int:
    """Mother-once following, then child ops; supports skip-sync when edges already present."""
    load_dotenv(REPO_ROOT / '.env')
    report = build_status(downloader_root=Path(args.downloader_root), seed_user_id=args.seed_user_id)
    if not args.json:
        report.print_human()
    if not report.payload['readiness']['ready'] and not args.force:
        print('未就绪。用 --force 可强行继续。', file=sys.stderr)
        return 2

    seed = resolve_seed_user_id(args.seed_user_id)
    if seed is None:
        print('缺少 seed_user_id', file=sys.stderr)
        return 2

    preset = dict(PRESETS[args.preset])
    for key in ('max_seed_artists', 'max_candidate_artists', 'followed_artist_limit', 'candidate_artist_limit', 'max_results', 'min_bookmarks'):
        value = getattr(args, key, None)
        if value is not None:
            preset[key] = value

    facade = _build_facade()
    following_edges = int(report.payload['database'].get('following_edges') or 0)
    skip_sync = args.skip_sync or (args.skip_sync_if_present and following_edges > 0)

    steps_done: list[dict[str, Any]] = []

    def note(name: str, payload: dict[str, Any]) -> None:
        compact = {k: payload.get(k) for k in list(payload)[:12]}
        steps_done.append({'step': name, 'payload': compact})
        print(f'--- {name} ---')
        print(json.dumps(compact, ensure_ascii=False, indent=2))

    try:
        if not skip_sync:
            print('>>> step: sync-following (mother token preferred)')
            note(
                'sync-following',
                facade.sync_following_payload(seed_user_id=seed),
            )
        else:
            print(f'>>> skip sync-following (following_edges={following_edges})')
            steps_done.append({'step': 'sync-following', 'skipped': True, 'following_edges': following_edges})

        print('>>> step: hydrate-followed-illusts (child, no re-sync)')
        note(
            'hydrate-followed-illusts',
            facade.hydrate_followed_illusts_payload(
                seed_user_id=seed,
                per_artist_limit=int(preset['followed_artist_limit']),
                max_artists=int(preset['max_seed_artists']),
                sync_following=False,
            ),
        )

        print('>>> step: build-profile')
        note('build-profile', facade.build_profile_payload(seed_user_id=seed))

        print('>>> step: build-candidates (child)')
        note(
            'build-candidates',
            facade.build_candidates_payload(
                seed_user_id=seed,
                max_related_per_artist=int(preset['max_related_per_artist']),
                max_related_per_illust=int(preset['max_related_per_illust']),
                max_seed_artists=int(preset['max_seed_artists']),
                max_user_recommended=int(preset['max_user_recommended']),
                max_tag_search_tags=int(preset['max_tag_search_tags']),
                max_tag_search_illusts=int(preset['max_tag_search_illusts']),
            ),
        )

        print('>>> step: hydrate-candidate-illusts (child)')
        note(
            'hydrate-candidate-illusts',
            facade.hydrate_candidate_illusts_payload(
                seed_user_id=seed,
                per_artist_limit=int(preset['candidate_artist_limit']),
                max_artists=int(preset['max_candidate_artists']),
            ),
        )

        print('>>> step: recommend-from-store')
        rec = facade.recommend_from_store_payload(
            seed_user_id=seed,
            max_results=int(preset['max_results']),
            diversity_per_tag=int(preset['diversity_per_tag']),
            min_bookmarks=int(preset['min_bookmarks']),
            min_score=float(preset['min_score']),
        )
        note('recommend-from-store', {'item_count': rec.get('item_count'), 'items': rec.get('items', [])[:10]})

        out_dir = REPO_ROOT / 'data' / 'local' / 'exports'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'steps-{seed}-recommend.json'
        out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'ok': True, 'output_path': str(out_path), 'item_count': rec.get('item_count'), 'steps': [s['step'] for s in steps_done]}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f'STEPS FAILED at after {steps_done[-1]["step"] if steps_done else "start"}: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


def interactive_menu(args: argparse.Namespace) -> int:
    report = build_status(downloader_root=Path(args.downloader_root), seed_user_id=args.seed_user_id)
    report.print_human()
    print()
    print('选择操作:')
    print('  1) 一键 full-recommend（daily 预设，适合 ~2600 关注抽样）')
    print('  2) 分步启动（母号只 sync 一次，可跳过已有关注）')
    print('  3) 深度扫描 deep')
    print('  4) 仅刷新状态')
    print('  5) 从 downloader 重新导入配置')
    print('  0) 退出')
    try:
        choice = input('> ').strip()
    except EOFError:
        return 0
    if choice == '1':
        args.preset = 'daily'
        return cmd_run(args)
    if choice == '2':
        args.preset = 'daily'
        args.skip_sync = False
        args.skip_sync_if_present = True
        return cmd_steps(args)
    if choice == '3':
        args.preset = 'deep'
        return cmd_run(args)
    if choice == '4':
        return cmd_status(args)
    if choice == '5':
        return cmd_import_config(args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='start.py', description='pixiv-artist-recsys local launcher')
    parser.add_argument('--downloader-root', default=str(DEFAULT_DOWNLOADER))
    parser.add_argument('--seed-user-id', type=int, default=0)
    parser.add_argument('--json', action='store_true', help='machine-readable status / less human noise')
    parser.add_argument('--force', action='store_true', help='run even if readiness checks fail')
    parser.add_argument('--preset', choices=sorted(PRESETS.keys()), default='daily')
    parser.add_argument('--max-seed-artists', type=int)
    parser.add_argument('--max-candidate-artists', type=int)
    parser.add_argument('--followed-artist-limit', type=int)
    parser.add_argument('--candidate-artist-limit', type=int)
    parser.add_argument('--max-results', type=int)
    parser.add_argument('--min-bookmarks', type=int)

    sub = parser.add_subparsers(dest='command')

    sub.add_parser('status', help='Show local status')
    run_p = sub.add_parser('run', help='One-click full-recommend')
    run_p.add_argument('--preset', choices=sorted(PRESETS.keys()), default='daily')
    run_p.add_argument('--force', action='store_true')
    run_p.add_argument('--max-seed-artists', type=int)
    run_p.add_argument('--max-candidate-artists', type=int)
    run_p.add_argument('--followed-artist-limit', type=int)
    run_p.add_argument('--candidate-artist-limit', type=int)
    run_p.add_argument('--max-results', type=int)
    run_p.add_argument('--min-bookmarks', type=int)
    run_p.add_argument('--seed-user-id', type=int, default=0)
    run_p.add_argument('--downloader-root', default=str(DEFAULT_DOWNLOADER))
    run_p.add_argument('--json', action='store_true')

    steps_p = sub.add_parser('steps', help='Step pipeline with mother-once following')
    steps_p.add_argument('--preset', choices=sorted(PRESETS.keys()), default='daily')
    steps_p.add_argument('--force', action='store_true')
    steps_p.add_argument('--skip-sync', action='store_true', help='never call sync-following')
    steps_p.add_argument('--skip-sync-if-present', action='store_true', default=True, help='skip sync if following edges exist (default on)')
    steps_p.add_argument('--always-sync', action='store_true', help='force mother following sync')
    steps_p.add_argument('--max-seed-artists', type=int)
    steps_p.add_argument('--max-candidate-artists', type=int)
    steps_p.add_argument('--followed-artist-limit', type=int)
    steps_p.add_argument('--candidate-artist-limit', type=int)
    steps_p.add_argument('--max-results', type=int)
    steps_p.add_argument('--min-bookmarks', type=int)
    steps_p.add_argument('--seed-user-id', type=int, default=0)
    steps_p.add_argument('--downloader-root', default=str(DEFAULT_DOWNLOADER))
    steps_p.add_argument('--json', action='store_true')

    imp = sub.add_parser('import-config', help='Import mother/child/proxy from downloader-personal')
    imp.add_argument('--downloader-root', default=str(DEFAULT_DOWNLOADER))
    imp.add_argument('--child-id', default='')
    imp.add_argument('--seed-user-id', type=int, default=0)

    return parser


def main(argv: list[str] | None = None) -> int:
    os.chdir(REPO_ROOT)
    ensure_sys_path()
    load_dotenv(REPO_ROOT / '.env')

    parser = build_parser()
    args = parser.parse_args(argv)

    # normalize nested defaults for subcommands
    if getattr(args, 'seed_user_id', 0) == 0:
        args.seed_user_id = 0
    if getattr(args, 'always_sync', False):
        args.skip_sync = False
        args.skip_sync_if_present = False

    command = args.command
    if command is None:
        return interactive_menu(args)
    if command == 'status':
        return cmd_status(args)
    if command == 'run':
        return cmd_run(args)
    if command == 'steps':
        return cmd_steps(args)
    if command == 'import-config':
        return cmd_import_config(args)
    parser.error(f'unknown command: {command}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
