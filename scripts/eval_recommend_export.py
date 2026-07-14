#!/usr/bin/env python3
"""Offline metrics for recommend-from-store / full-recommend JSON exports.

Usage:
  python scripts/eval_recommend_export.py data/local/exports/steps-51850385-recommend.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


GENRE_MARKERS = {
    'manga': ('漫画', 'manga', '4コマ', '4koma', 'コミック', 'comic'),
    'furry': ('ケモノ', 'ケモ', 'furry', 'anthro', '獣人', '獣化'),
    'bl': ('創作bl', 'ボーイズラブ', 'boys_love', 'やおい', 'yaoi', '腐向け', 'bl'),
}
GENERIC_TAGS = {'女の子', 'オリジナル', 'original', 'girl', 'girls', 'イラスト', 'illustration', '創作'}


def _tags_from_reasons(reasons: list[str]) -> list[str]:
    for reason in reasons:
        if reason.startswith('tags:'):
            return [part for part in reason[5:].split(',') if part]
    return []


def _sources_from_reasons(reasons: list[str]) -> list[str]:
    return [reason.split(':', 1)[1] for reason in reasons if reason.startswith('evidence:')]


def evaluate(payload: dict) -> dict:
    items = payload.get('items') or []
    source_counter: Counter[str] = Counter()
    genre_hits: Counter[str] = Counter()
    primary_counter: Counter[str] = Counter()
    generic_primary = 0
    scored = 0
    for item in items:
        reasons = list(item.get('reasons') or [])
        for source in _sources_from_reasons(reasons):
            source_counter[source] += 1
        tags = _tags_from_reasons(reasons)
        joined = ' '.join(tags).lower()
        for family, markers in GENRE_MARKERS.items():
            if any(marker.lower() in joined for marker in markers):
                genre_hits[family] += 1
        primary = tags[0] if tags else ''
        if primary:
            primary_counter[primary] += 1
        if primary in GENERIC_TAGS:
            generic_primary += 1
        scored += 1

    n = max(1, scored)
    violation = sum(genre_hits.values())
    return {
        'seed_user_id': payload.get('seed_user_id'),
        'item_count': scored,
        'filters': payload.get('filters') or {},
        'source_counts': dict(source_counter),
        'genre_violations': dict(genre_hits),
        'genre_violation_rate': round(violation / n, 4),
        'generic_primary_rate': round(generic_primary / n, 4),
        'top_primary_tags': primary_counter.most_common(10),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: eval_recommend_export.py <export.json> [...]', file=sys.stderr)
        return 2
    for path_text in argv[1:]:
        path = Path(path_text)
        payload = json.loads(path.read_text(encoding='utf-8'))
        report = evaluate(payload)
        print(f'=== {path} ===')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
