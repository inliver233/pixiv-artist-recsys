from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(slots=True)
class ConsensusArtist:
    artist_user_id: int
    hit_count: int
    round_count: int
    rounds: list[int]
    best_score: float
    mean_score: float
    mean_confidence: float
    consensus_score: float
    name: str
    account: str
    reasons: list[str]
    top_illust_ids: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            'artist_user_id': self.artist_user_id,
            'hit_count': self.hit_count,
            'round_count': self.round_count,
            'rounds': list(self.rounds),
            'best_score': self.best_score,
            'mean_score': self.mean_score,
            'mean_confidence': self.mean_confidence,
            'consensus_score': self.consensus_score,
            'name': self.name,
            'account': self.account,
            'reasons': list(self.reasons),
            'top_illust_ids': list(self.top_illust_ids),
        }


def _item_artist_id(item: Mapping[str, Any] | Any) -> int:
    if isinstance(item, Mapping):
        if 'artist_user_id' in item:
            return int(item['artist_user_id'])
        artist = item.get('artist') or {}
        if isinstance(artist, Mapping) and 'user_id' in artist:
            return int(artist['user_id'])
        if hasattr(artist, 'user_id'):
            return int(artist.user_id)
    if hasattr(item, 'artist') and hasattr(item.artist, 'user_id'):
        return int(item.artist.user_id)
    raise ValueError('consensus item missing artist_user_id')


def _item_score(item: Mapping[str, Any] | Any) -> float:
    if isinstance(item, Mapping):
        return float(item.get('score') or 0.0)
    return float(getattr(item, 'score', 0.0) or 0.0)


def _item_confidence(item: Mapping[str, Any] | Any) -> float:
    if isinstance(item, Mapping):
        return float(item.get('confidence') or 0.0)
    return float(getattr(item, 'confidence', 0.0) or 0.0)


def _item_name(item: Mapping[str, Any] | Any) -> str:
    if isinstance(item, Mapping):
        if item.get('name'):
            return str(item['name'])
        artist = item.get('artist') or {}
        if isinstance(artist, Mapping):
            return str(artist.get('name') or '')
        return str(getattr(artist, 'name', '') or '')
    artist = getattr(item, 'artist', None)
    return str(getattr(artist, 'name', '') or '')


def _item_account(item: Mapping[str, Any] | Any) -> str:
    if isinstance(item, Mapping):
        if item.get('account'):
            return str(item['account'])
        artist = item.get('artist') or {}
        if isinstance(artist, Mapping):
            return str(artist.get('account') or '')
        return str(getattr(artist, 'account', '') or '')
    artist = getattr(item, 'artist', None)
    return str(getattr(artist, 'account', '') or '')


def _item_reasons(item: Mapping[str, Any] | Any) -> list[str]:
    if isinstance(item, Mapping):
        raw = item.get('reasons') or []
        return [str(x) for x in raw]
    return [str(x) for x in (getattr(item, 'reasons', None) or [])]


def _item_top_illusts(item: Mapping[str, Any] | Any) -> list[int]:
    if isinstance(item, Mapping):
        raw = item.get('top_illust_ids') or []
        return [int(x) for x in raw]
    return [int(x) for x in (getattr(item, 'top_illust_ids', None) or [])]


def build_multi_round_consensus(
    round_item_lists: Sequence[Sequence[Mapping[str, Any] | Any]],
    *,
    min_hits: int = 2,
    max_results: int = 500,
    hit_weight: float = 0.55,
    mean_score_weight: float = 0.30,
    best_score_weight: float = 0.15,
) -> list[ConsensusArtist]:
    """Rank artists by multi-round overlap + score stability.

    Artists appearing in more independent rounds are higher-confidence (not just
    one lucky seed sample). Score formula (weights sum to 1):

        consensus = hit_w * (hits/rounds) + mean_w * mean_score + best_w * best_score

    ``min_hits`` filters one-off noise; set to 1 to keep the full union.
    """
    if not round_item_lists:
        return []
    round_count = len(round_item_lists)
    scores: dict[int, list[float]] = defaultdict(list)
    confs: dict[int, list[float]] = defaultdict(list)
    rounds_hit: dict[int, list[int]] = defaultdict(list)
    names: dict[int, str] = {}
    accounts: dict[int, str] = {}
    reasons: dict[int, list[str]] = {}
    tops: dict[int, list[int]] = {}

    for round_index, items in enumerate(round_item_lists):
        seen_this_round: set[int] = set()
        for item in items:
            artist_id = _item_artist_id(item)
            if artist_id <= 0 or artist_id in seen_this_round:
                continue
            seen_this_round.add(artist_id)
            scores[artist_id].append(_item_score(item))
            confs[artist_id].append(_item_confidence(item))
            rounds_hit[artist_id].append(round_index)
            names[artist_id] = _item_name(item) or names.get(artist_id, '')
            accounts[artist_id] = _item_account(item) or accounts.get(artist_id, '')
            if artist_id not in reasons:
                reasons[artist_id] = _item_reasons(item)
            if artist_id not in tops:
                tops[artist_id] = _item_top_illusts(item)

    hw = max(0.0, float(hit_weight))
    mw = max(0.0, float(mean_score_weight))
    bw = max(0.0, float(best_score_weight))
    weight_sum = hw + mw + bw or 1.0
    hw, mw, bw = hw / weight_sum, mw / weight_sum, bw / weight_sum

    results: list[ConsensusArtist] = []
    for artist_id, score_list in scores.items():
        hits = len(score_list)
        if hits < max(1, int(min_hits)):
            continue
        best = max(score_list)
        mean = sum(score_list) / hits
        mean_conf = sum(confs[artist_id]) / hits if confs[artist_id] else 0.0
        hit_rate = hits / float(round_count)
        consensus = hw * hit_rate + mw * max(0.0, min(1.0, mean)) + bw * max(0.0, min(1.0, best))
        hit_reasons = [
            f'consensus:hits={hits}/{round_count}',
            f'consensus:rounds={",".join(str(r) for r in rounds_hit[artist_id])}',
            f'consensus:score={round(consensus, 4)}',
        ]
        results.append(
            ConsensusArtist(
                artist_user_id=artist_id,
                hit_count=hits,
                round_count=round_count,
                rounds=list(rounds_hit[artist_id]),
                best_score=round(best, 6),
                mean_score=round(mean, 6),
                mean_confidence=round(mean_conf, 6),
                consensus_score=round(consensus, 6),
                name=names.get(artist_id, ''),
                account=accounts.get(artist_id, ''),
                reasons=hit_reasons + list(reasons.get(artist_id, [])[:6]),
                top_illust_ids=list(tops.get(artist_id, [])[:3]),
            )
        )

    results.sort(key=lambda row: (-row.consensus_score, -row.hit_count, -row.best_score, row.artist_user_id))
    limit = max(0, int(max_results))
    return results[:limit] if limit else results


def extract_round_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize a full-recommend / recommend-from-store payload into consensus items."""
    items = payload.get('items') or []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        artist_id = item.get('artist_user_id')
        if artist_id is None:
            artist = item.get('artist') or {}
            if isinstance(artist, Mapping):
                artist_id = artist.get('user_id')
        if artist_id is None:
            continue
        name = str(item.get('name') or '')
        account = str(item.get('account') or '')
        if not name:
            artist = item.get('artist') or {}
            if isinstance(artist, Mapping):
                name = str(artist.get('name') or '')
                account = account or str(artist.get('account') or '')
        out.append(
            {
                'artist_user_id': int(artist_id),
                'score': float(item.get('score') or 0.0),
                'confidence': float(item.get('confidence') or 0.0),
                'name': name,
                'account': account,
                'reasons': list(item.get('reasons') or []),
                'top_illust_ids': [int(x) for x in (item.get('top_illust_ids') or [])],
            }
        )
    return out


def campaign_seed_plan(*, rounds: int) -> list[dict[str, Any]]:
    """Per-round sampling plan so multi-round coverage is intentional, not accidental.

    Alternates quality_first (salted) with random / hash so exploit + explore both
    contribute to the consensus pool.
    """
    n = max(1, int(rounds))
    plan: list[dict[str, Any]] = []
    modes = ('quality_first', 'quality_first', 'random', 'hash')
    explores = (0.25, 0.40, 0.0, 0.0)
    for i in range(n):
        mode = modes[i % len(modes)]
        plan.append(
            {
                'round_index': i,
                'sample_salt': i + 1,
                'seed_sample': mode,
                'seed_following_sample': mode if mode != 'hash' else 'quality_first',
                'explore_ratio': explores[i % len(explores)],
            }
        )
    return plan
