from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from ..domain.models import Artist, Illust
from ..pixiv import PixivAppApiClient
from ..pixiv.models import PixivIllustSummary
from ..storage.repositories import RecommendationRepository
from ..utils.progress import ProgressCallback, emit
from ..utils.sampling import sample_ids

# Recently hydrated artists are skipped (their portfolios barely move week to week).
DEFAULT_HYDRATE_TTL_S = 10 * 86400.0

# Hydration budget shares per dominant recall source (x-algorithm quota model).
# Hydration IS the real recall — 94% of candidates died unhydrated in the field —
# so the budget split is enforced here, not at fetch time. Normalized at use.
DEFAULT_SOURCE_QUOTAS: dict[str, float] = {
    'user_related': 0.40,
    'illust_related': 0.25,
    'seed_artist_following': 0.20,
    'user_recommended': 0.10,
    'tag_search': 0.05,
    'graph_ppr': 0.10,
    'graph_jaccard': 0.05,
}


@dataclass(slots=True)
class ArtistIllustHydrationResult:
    seed_user_id: int
    artists_processed: int
    illusts_upserted: int
    scope: str = 'followed'
    detail_fetches: int = 0
    list_only_saves: int = 0
    skipped_fresh: int = 0
    failed_artists: int = 0


class ArtistIllustHydrationService:
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        pixiv_client: PixivAppApiClient,
        now_fn: Callable[[], float] | None = None,
        freshness_max_age_s: float = DEFAULT_HYDRATE_TTL_S,
        skip_min_local_illusts: int = 2,
    ) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client
        self.now_fn = now_fn or time.time
        self.freshness_max_age_s = float(freshness_max_age_s)
        self.skip_min_local_illusts = int(skip_min_local_illusts)

    def hydrate_followed_artists(
        self,
        *,
        seed_user_id: int,
        per_artist_limit: int = 10,
        max_artists: int | None = 90,
        seed_sample: str = 'random',
        sample_salt: int | str | None = None,
        explore_ratio: float = 0.25,
        on_progress: ProgressCallback | None = None,
    ) -> ArtistIllustHydrationResult:
        artists = self.repository.list_followed_artists(seed_user_id=seed_user_id)
        artist_ids = [artist.user_id for artist in artists]
        artist_ids, skipped_fresh = self._drop_fresh(artist_ids, on_progress=on_progress, scope='followed')
        if max_artists is not None:
            quality_scores = self._quality_scores(artist_ids)
            artist_ids = sample_ids(
                artist_ids,
                seed_user_id=seed_user_id,
                limit=max(0, int(max_artists)),
                mode=seed_sample,
                quality_scores=quality_scores,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )
        return self._hydrate_artist_ids(
            seed_user_id=seed_user_id,
            artist_user_ids=artist_ids,
            per_artist_limit=per_artist_limit,
            scope='followed',
            skipped_fresh=skipped_fresh,
            on_progress=on_progress,
        )

    def hydrate_candidate_artists(
        self,
        *,
        seed_user_id: int,
        per_artist_limit: int = 6,
        max_artists: int | None = 130,
        seed_sample: str = 'random',
        sample_salt: int | str | None = None,
        explore_ratio: float = 0.25,
        source_quotas: dict[str, float] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ArtistIllustHydrationResult:
        followed_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        candidate_ids = []
        for artist_user_id in self.repository.list_candidate_artist_ids(seed_user_id=seed_user_id):
            if artist_user_id in followed_ids:
                continue
            if self.repository.fetch_artist(artist_user_id=artist_user_id) is None:
                self.repository.upsert_artist(Artist(user_id=artist_user_id, name=f'artist-{artist_user_id}', is_followed=False))
            candidate_ids.append(artist_user_id)
        candidate_ids, skipped_fresh = self._drop_fresh(candidate_ids, on_progress=on_progress, scope='candidate')
        if max_artists is not None:
            candidate_ids = self._select_candidates_with_quota(
                seed_user_id=seed_user_id,
                candidate_ids=candidate_ids,
                limit=max(0, int(max_artists)),
                seed_sample=seed_sample,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
                source_quotas=source_quotas if source_quotas is not None else DEFAULT_SOURCE_QUOTAS,
                on_progress=on_progress,
            )
        return self._hydrate_artist_ids(
            seed_user_id=seed_user_id,
            artist_user_ids=candidate_ids,
            per_artist_limit=per_artist_limit,
            scope='candidate',
            skipped_fresh=skipped_fresh,
            on_progress=on_progress,
        )

    def _select_candidates_with_quota(
        self,
        *,
        seed_user_id: int,
        candidate_ids: list[int],
        limit: int,
        seed_sample: str,
        sample_salt: int | str | None,
        explore_ratio: float,
        source_quotas: dict[str, float] | None,
        on_progress: ProgressCallback | None = None,
    ) -> list[int]:
        """Split the hydration budget across recall sources by quota.

        Each candidate belongs to its highest-weight evidence source. Every
        source bucket gets quota*limit slots (sampled within the bucket by the
        usual priority mode); unused slots spill over to the global pool so the
        budget is always filled. Empty/None quotas = legacy global sampling.
        """
        if limit <= 0 or not candidate_ids:
            return []
        quality_scores = self._candidate_priority_scores(seed_user_id=seed_user_id, candidate_ids=candidate_ids)
        if not source_quotas or limit >= len(candidate_ids):
            return sample_ids(
                candidate_ids,
                seed_user_id=seed_user_id,
                limit=limit,
                mode=seed_sample,
                quality_scores=quality_scores,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )

        dominant: dict[int, str] = {}
        best_weight: dict[int, float] = {}
        for candidate_user_id, source_type, _source_key, weight, _detail in self.repository.fetch_artist_candidates(
            seed_user_id=seed_user_id
        ):
            cid = int(candidate_user_id)
            if cid not in quality_scores:
                continue
            if float(weight) > best_weight.get(cid, -1.0):
                best_weight[cid] = float(weight)
                dominant[cid] = str(source_type)

        buckets: dict[str, list[int]] = defaultdict(list)
        for cid in candidate_ids:
            buckets[dominant.get(int(cid), 'unknown')].append(int(cid))

        total_quota = sum(max(0.0, q) for src, q in source_quotas.items() if src in buckets) or 1.0
        selected: list[int] = []
        chosen: set[int] = set()
        for source, ids in sorted(buckets.items(), key=lambda kv: -source_quotas.get(kv[0], 0.0)):
            share = max(0.0, source_quotas.get(source, 0.0)) / total_quota
            bucket_limit = int(round(limit * share))
            if bucket_limit <= 0:
                continue
            picked = sample_ids(
                ids,
                seed_user_id=seed_user_id,
                limit=min(bucket_limit, len(ids)),
                mode=seed_sample,
                quality_scores=quality_scores,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )
            for cid in picked:
                if cid not in chosen:
                    chosen.add(cid)
                    selected.append(cid)
        if len(selected) < limit:
            # Spill: fill remaining slots from the global pool by priority.
            remaining = [cid for cid in candidate_ids if cid not in chosen]
            filler = sample_ids(
                remaining,
                seed_user_id=seed_user_id,
                limit=limit - len(selected),
                mode=seed_sample,
                quality_scores=quality_scores,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )
            selected.extend(filler)
        emit(
            on_progress,
            stage='hydrate_candidate',
            event='info',
            message=(
                'quota split: '
                + ', '.join(f'{src}={len(ids)}' for src, ids in sorted(buckets.items()))
                + f' -> selected={len(selected[:limit])}'
            ),
            scope='candidate',
        )
        return selected[:limit]

    def _drop_fresh(
        self,
        artist_ids: list[int],
        *,
        scope: str,
        on_progress: ProgressCallback | None = None,
    ) -> tuple[list[int], int]:
        """Skip-if-fresh: remove recently hydrated artists so budget goes to stale ones."""
        if self.freshness_max_age_s <= 0 or not artist_ids:
            return artist_ids, 0
        fresh = self.repository.fetch_fresh_artist_ids(
            artist_user_ids=artist_ids,
            max_age_s=self.freshness_max_age_s,
            now_epoch=float(self.now_fn()),
            min_local_illusts=self.skip_min_local_illusts,
        )
        if not fresh:
            return artist_ids, 0
        remaining = [artist_id for artist_id in artist_ids if artist_id not in fresh]
        emit(
            on_progress,
            stage=f'hydrate_{scope}',
            event='info',
            message=f'skip-if-fresh: {len(fresh)} artists hydrated recently, {len(remaining)} remain',
            scope=scope,
            skipped_fresh=len(fresh),
        )
        return remaining, len(fresh)

    def _quality_scores(self, artist_ids: list[int]) -> dict[int, float]:
        max_bm = self.repository.fetch_max_bookmarks_by_artist(artist_user_ids=[int(a) for a in artist_ids])
        return {int(artist_id): float(max_bm.get(int(artist_id), 0)) for artist_id in artist_ids}

    def _candidate_priority_scores(self, *, seed_user_id: int, candidate_ids: list[int]) -> dict[int, float]:
        """Score candidates for hydrate sampling: evidence weight sum + local max bookmarks."""
        weight_sum: dict[int, float] = {int(cid): 0.0 for cid in candidate_ids}
        for candidate_user_id, _source_type, _source_key, weight, _detail in self.repository.fetch_artist_candidates(
            seed_user_id=seed_user_id
        ):
            cid = int(candidate_user_id)
            if cid in weight_sum:
                weight_sum[cid] += float(weight)
        max_bm = self.repository.fetch_max_bookmarks_by_artist(artist_user_ids=[int(c) for c in candidate_ids])
        # Evidence first so multi-source unhydrated candidates still get hydrated.
        return {
            int(cid): float(weight_sum.get(int(cid), 0.0)) * 1000.0 + float(max_bm.get(int(cid), 0))
            for cid in candidate_ids
        }

    def _hydrate_artist_ids(
        self,
        *,
        seed_user_id: int,
        artist_user_ids: list[int],
        per_artist_limit: int,
        scope: str,
        skipped_fresh: int = 0,
        on_progress: ProgressCallback | None = None,
    ) -> ArtistIllustHydrationResult:
        stage = f'hydrate_{scope}'
        total = len(artist_user_ids)
        emit(
            on_progress,
            stage=stage,
            event='start',
            current=0,
            total=total,
            message=f'hydrate {scope}: {total} artists × up to {per_artist_limit} illusts',
            scope=scope,
            per_artist_limit=per_artist_limit,
        )
        illusts_upserted = 0
        detail_fetches = 0
        list_only_saves = 0
        failed_artists = 0
        for index, artist_user_id in enumerate(artist_user_ids, start=1):
            # Per-artist fault tolerance: one deleted/404 account must not sink
            # a run that already spent hours (retry layer only covers 429/5xx).
            try:
                page = self.pixiv_client.fetch_user_illusts(user_id=artist_user_id)
            except Exception as exc:  # noqa: BLE001 - single-artist failure is survivable
                failed_artists += 1
                emit(
                    on_progress,
                    stage=stage,
                    event='info',
                    message=f'{scope} artist {index}/{total} id={artist_user_id} skipped ({type(exc).__name__})',
                    artist_user_id=artist_user_id,
                    scope=scope,
                    failed_artists=failed_artists,
                )
                continue
            artist_illusts = 0
            # Fetch details first, then persist the artist's batch in one transaction.
            details_by_illust: dict[int, object] = {}
            selected = list(page.items[:per_artist_limit])
            detail_failed = False
            for summary in selected:
                # user_illusts list payload usually already has tags + ai/r18 flags.
                # Skip illust/detail when tags are present → ~half the hydrate API volume.
                if not summary.tags:
                    try:
                        details_by_illust[summary.illust_id] = self.pixiv_client.fetch_illust_detail(
                            illust_id=summary.illust_id
                        )
                    except Exception as exc:  # noqa: BLE001 - skip this artist, keep the run
                        detail_failed = True
                        failed_artists += 1
                        emit(
                            on_progress,
                            stage=stage,
                            event='info',
                            message=(
                                f'{scope} artist {index}/{total} id={artist_user_id} '
                                f'detail fetch failed ({type(exc).__name__}), skipped'
                            ),
                            artist_user_id=artist_user_id,
                            scope=scope,
                            failed_artists=failed_artists,
                        )
                        break
                    detail_fetches += 1
            if detail_failed:
                continue
            with self.repository.transaction():
                self.repository.mark_artist_hydrated(
                    artist_user_id=artist_user_id, now_epoch=float(self.now_fn())
                )
                for summary in selected:
                    detail = details_by_illust.get(summary.illust_id)
                    if detail is None:
                        list_only_saves += 1
                        self._upsert_from_summary(summary)
                    else:
                        self.repository.upsert_illust(
                            Illust(
                                illust_id=detail.illust.illust_id,
                                user_id=detail.illust.user_id,
                                title=detail.illust.title,
                                create_date=detail.illust.create_date,
                                total_bookmarks=detail.illust.total_bookmarks,
                                total_view=detail.illust.total_view,
                                total_comments=detail.illust.total_comments,
                                ai_type=detail.ai_type,
                                x_restrict=detail.x_restrict,
                                illust_type=detail.illust.illust_type or '',
                                page_count=max(1, int(detail.page_count or detail.illust.page_count or 1)),
                            )
                        )
                        self.repository.replace_illust_tags(illust_id=detail.illust.illust_id, tags=detail.tags)
                    illusts_upserted += 1
                    artist_illusts += 1
            emit(
                on_progress,
                stage=stage,
                event='progress',
                current=index,
                total=total,
                message=f'{scope} artist {index}/{total} id={artist_user_id} +{artist_illusts} illusts',
                artist_user_id=artist_user_id,
                artist_illusts=artist_illusts,
                illusts_upserted=illusts_upserted,
                detail_fetches=detail_fetches,
                list_only_saves=list_only_saves,
                scope=scope,
            )
        emit(
            on_progress,
            stage=stage,
            event='done',
            current=total,
            total=total,
            message=(
                f'done {scope}: artists={total} illusts={illusts_upserted} '
                f'(list_only={list_only_saves} detail={detail_fetches})'
            ),
            artists_processed=total,
            illusts_upserted=illusts_upserted,
            detail_fetches=detail_fetches,
            list_only_saves=list_only_saves,
            scope=scope,
        )
        return ArtistIllustHydrationResult(
            seed_user_id=seed_user_id,
            artists_processed=len(artist_user_ids),
            illusts_upserted=illusts_upserted,
            scope=scope,
            detail_fetches=detail_fetches,
            list_only_saves=list_only_saves,
            skipped_fresh=skipped_fresh,
            failed_artists=failed_artists,
        )

    def _upsert_from_summary(self, summary: PixivIllustSummary) -> None:
        self.repository.upsert_illust(
            Illust(
                illust_id=summary.illust_id,
                user_id=summary.user_id,
                title=summary.title,
                create_date=summary.create_date,
                total_bookmarks=summary.total_bookmarks,
                total_view=summary.total_view,
                total_comments=summary.total_comments,
                ai_type=summary.ai_type,
                x_restrict=summary.x_restrict,
                illust_type=summary.illust_type or '',
                page_count=max(1, int(summary.page_count or 1)),
                image_url=str(getattr(summary, 'image_url', '') or ''),
            )
        )
        self.repository.replace_illust_tags(illust_id=summary.illust_id, tags=list(summary.tags or []))
