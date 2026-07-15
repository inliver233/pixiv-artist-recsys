from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Artist
from ..pixiv import PixivAppApiClient
from ..storage.repositories import RecommendationRepository
from ..utils.progress import ProgressCallback, emit
from ..utils.sampling import hash_sample_ids, sample_ids


# Evidence weights (ranker further damps by source reliability).
# following expand is broad/noisy → keep weight below related so it cannot flood tops.
WEIGHT_USER_RELATED = 1.0
WEIGHT_ILLUST_RELATED = 0.85
WEIGHT_USER_RECOMMENDED = 0.9
WEIGHT_TAG_SEARCH = 0.7
WEIGHT_SEED_ARTIST_FOLLOWING = 0.55

# Tags too generic for search recall (profile may still keep them at low weight).
TAG_SEARCH_BLOCKLIST: frozenset[str] = frozenset(
    {
        '女の子',
        'オリジナル',
        'original',
        'girl',
        'girls',
        'イラスト',
        'illustration',
        '創作',
        '風景',
        '背景',
        'r-18',
        'r18',
        'お品書き',
    }
)


@dataclass(slots=True)
class CandidateArtistResult:
    seed_user_id: int
    candidate_count: int
    evidence_count: int


class RelatedArtistCandidateService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

    def build_candidates(
        self,
        *,
        seed_user_id: int,
        max_related_per_artist: int = 8,
        max_related_per_illust: int = 8,
        max_seed_artists: int = 40,
        seed_sample: str = 'random',
        enable_user_recommended: bool = True,
        max_user_recommended: int = 30,
        enable_tag_search: bool = True,
        max_tag_search_tags: int = 5,
        max_tag_search_illusts: int = 20,
        enable_seed_following: bool = True,
        max_seed_following_artists: int = 12,
        max_following_per_seed_artist: int = 30,
        seed_following_sample: str = 'random',
        seed_following_restrict: str = 'public',
        merge_candidates: bool = False,
        sample_salt: int | str | None = None,
        explore_ratio: float = 0.25,
        on_progress: ProgressCallback | None = None,
    ) -> CandidateArtistResult:
        followed_artist_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        evidence_rows: list[tuple[int, str, str, float, str]] = []
        hydrated_artist_cache: dict[int, Artist] = {}
        quality_scores = self._followed_quality_scores(followed_artist_ids)
        # quality_first prefers high-bookmark followed artists as recall seeds.
        seed_artist_ids = sample_ids(
            followed_artist_ids,
            seed_user_id=seed_user_id,
            limit=max(0, int(max_seed_artists)),
            mode=seed_sample,
            quality_scores=quality_scores,
            sample_salt=sample_salt,
            explore_ratio=explore_ratio,
        )
        total_seeds = len(seed_artist_ids)

        emit(
            on_progress,
            stage='candidates',
            event='start',
            current=0,
            total=total_seeds,
            message=(
                f'build candidates from {total_seeds} seed artists '
                f'(seed_following={enable_seed_following})'
            ),
            max_seed_artists=max_seed_artists,
            enable_user_recommended=enable_user_recommended,
            enable_tag_search=enable_tag_search,
            enable_seed_following=enable_seed_following,
        )

        for index, artist_id in enumerate(seed_artist_ids, start=1):
            related_users = self.pixiv_client.fetch_user_related(seed_user_id=artist_id)
            for user in related_users.items[:max_related_per_artist]:
                self._accept_user_candidate(
                    user=user,
                    followed_artist_ids=followed_artist_ids,
                    hydrated_artist_cache=hydrated_artist_cache,
                    evidence_rows=evidence_rows,
                    source_type='user_related',
                    source_key=f'user:{artist_id}',
                    weight=WEIGHT_USER_RELATED,
                    detail=f'related-to-user:{artist_id}',
                )

            for illust_id in self.repository.list_illust_ids_for_artist(artist_user_id=artist_id)[:max_related_per_artist]:
                related_illusts = self.pixiv_client.fetch_illust_related(illust_id=illust_id)
                for illust in related_illusts.items[:max_related_per_illust]:
                    if illust.user_id in followed_artist_ids or illust.user_id <= 0 or illust.user_id == seed_user_id:
                        continue
                    if illust.user_id not in hydrated_artist_cache:
                        existing = self.repository.fetch_artist(artist_user_id=illust.user_id)
                        hydrated_artist_cache[illust.user_id] = existing or Artist(
                            user_id=illust.user_id,
                            name=f'artist-{illust.user_id}',
                            is_followed=False,
                        )
                    evidence_rows.append(
                        (illust.user_id, 'illust_related', f'illust:{illust_id}', WEIGHT_ILLUST_RELATED, f'related-to-illust:{illust_id}')
                    )

            emit(
                on_progress,
                stage='candidates',
                event='progress',
                current=index,
                total=total_seeds,
                message=f'related seed {index}/{total_seeds} id={artist_id} evidence={len(evidence_rows)}',
                seed_artist_id=artist_id,
                evidence_count=len(evidence_rows),
                candidate_count=len(hydrated_artist_cache),
                phase='related',
            )

        if enable_seed_following and hasattr(self.pixiv_client, 'fetch_following_users'):
            expand_ids = self._select_seed_artists_for_following_expand(
                pool_ids=seed_artist_ids,
                seed_user_id=seed_user_id,
                max_artists=max(0, int(max_seed_following_artists)),
                sample_mode=seed_following_sample,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )
            emit(
                on_progress,
                stage='candidates',
                event='info',
                message=(
                    f'seed_following expand {len(expand_ids)} artists × up to '
                    f'{max_following_per_seed_artist} public follows (mode={seed_following_sample})'
                ),
                phase='seed_following',
                expand_count=len(expand_ids),
                sample_mode=seed_following_sample,
            )
            per_cap = max(0, int(max_following_per_seed_artist))
            for expand_index, artist_id in enumerate(expand_ids, start=1):
                taken = 0
                offset = 0
                try:
                    while taken < per_cap:
                        page = self.pixiv_client.fetch_following_users(
                            user_id=artist_id,
                            restrict=seed_following_restrict or 'public',
                            offset=offset if offset else None,
                        )
                        if not page.items:
                            break
                        for user in page.items:
                            if taken >= per_cap:
                                break
                            accepted = self._accept_user_candidate(
                                user=user,
                                followed_artist_ids=followed_artist_ids,
                                hydrated_artist_cache=hydrated_artist_cache,
                                evidence_rows=evidence_rows,
                                source_type='seed_artist_following',
                                source_key=f'following-of:{artist_id}',
                                weight=WEIGHT_SEED_ARTIST_FOLLOWING,
                                detail=f'seed-artist-following:{artist_id}',
                                also_skip_user_id=seed_user_id,
                            )
                            if accepted:
                                taken += 1
                        if not page.next_url or taken >= per_cap:
                            break
                        offset += len(page.items)
                except Exception:  # noqa: BLE001 - optional high-quality source must not break pipeline
                    emit(
                        on_progress,
                        stage='candidates',
                        event='info',
                        message=f'seed_following skip artist={artist_id} (api error)',
                        phase='seed_following',
                        seed_artist_id=artist_id,
                    )
                emit(
                    on_progress,
                    stage='candidates',
                    event='progress',
                    current=expand_index,
                    total=len(expand_ids),
                    message=(
                        f'seed_following {expand_index}/{len(expand_ids)} '
                        f'from={artist_id} +{taken} evidence={len(evidence_rows)}'
                    ),
                    phase='seed_following',
                    seed_artist_id=artist_id,
                    taken=taken,
                    evidence_count=len(evidence_rows),
                )

        if enable_user_recommended and hasattr(self.pixiv_client, 'fetch_user_recommended'):
            emit(
                on_progress,
                stage='candidates',
                event='info',
                message='fetch user_recommended feed',
                phase='user_recommended',
            )
            try:
                recommended = self.pixiv_client.fetch_user_recommended()
            except Exception:  # noqa: BLE001 - optional source must not break related recall
                recommended = None
            if recommended is not None:
                for user in recommended.items[: max(0, int(max_user_recommended))]:
                    self._accept_user_candidate(
                        user=user,
                        followed_artist_ids=followed_artist_ids,
                        hydrated_artist_cache=hydrated_artist_cache,
                        evidence_rows=evidence_rows,
                        source_type='user_recommended',
                        source_key='feed:user_recommended',
                        weight=WEIGHT_USER_RECOMMENDED,
                        detail='pixiv-user-recommended',
                        also_skip_user_id=seed_user_id,
                    )

        if enable_tag_search and hasattr(self.pixiv_client, 'fetch_search_illust'):
            profile = self.repository.fetch_user_taste_profile(seed_user_id=seed_user_id)
            # Skip pure-generic tags; take next distinctive tags up to the budget.
            top_tags: list[str] = []
            for tag, _weight in list(profile):
                normalized = str(tag or '').strip().lower()
                if not normalized or normalized in TAG_SEARCH_BLOCKLIST:
                    continue
                top_tags.append(tag)
                if len(top_tags) >= max(0, int(max_tag_search_tags)):
                    break
            emit(
                on_progress,
                stage='candidates',
                event='info',
                message=f'tag_search {len(top_tags)} tags',
                phase='tag_search',
                tag_count=len(top_tags),
            )
            for tag_index, tag in enumerate(top_tags, start=1):
                word = str(tag or '').replace('_', ' ').strip()
                if not word:
                    continue
                try:
                    page = self.pixiv_client.fetch_search_illust(word=word, sort='popular_desc')
                except Exception:  # noqa: BLE001 - optional source must not break related recall
                    continue
                for illust in page.items[: max(0, int(max_tag_search_illusts))]:
                    if illust.user_id in followed_artist_ids or illust.user_id <= 0 or illust.user_id == seed_user_id:
                        continue
                    if illust.user_id not in hydrated_artist_cache:
                        existing = self.repository.fetch_artist(artist_user_id=illust.user_id)
                        hydrated_artist_cache[illust.user_id] = existing or Artist(
                            user_id=illust.user_id,
                            name=f'artist-{illust.user_id}',
                            is_followed=False,
                        )
                    # One evidence row per (artist, tag); multiple illusts by same artist share source_key.
                    evidence_rows.append(
                        (
                            illust.user_id,
                            'tag_search',
                            f'tag:{word}',
                            WEIGHT_TAG_SEARCH,
                            f'search-illust-tag:{word}',
                        )
                    )
                emit(
                    on_progress,
                    stage='candidates',
                    event='progress',
                    current=tag_index,
                    total=len(top_tags),
                    message=f'tag {tag_index}/{len(top_tags)} "{word}" evidence={len(evidence_rows)}',
                    phase='tag_search',
                    tag=word,
                    evidence_count=len(evidence_rows),
                )

        for artist in hydrated_artist_cache.values():
            self.repository.upsert_artist(artist)
        self.repository.replace_artist_candidates(
            seed_user_id=seed_user_id,
            candidates=evidence_rows,
            merge=bool(merge_candidates),
        )
        # After merge, report store totals so progress reflects accumulated pool.
        stored = self.repository.fetch_artist_candidates(seed_user_id=seed_user_id)
        candidate_count = len({row[0] for row in stored}) if merge_candidates else len({row[0] for row in evidence_rows})
        evidence_count = len(stored) if merge_candidates else len(evidence_rows)
        emit(
            on_progress,
            stage='candidates',
            event='done',
            current=total_seeds,
            total=total_seeds,
            message=(
                f'done candidates={candidate_count} evidence={evidence_count}'
                f'{" (merged)" if merge_candidates else ""}'
            ),
            candidate_count=candidate_count,
            evidence_count=evidence_count,
            merge_candidates=bool(merge_candidates),
        )
        return CandidateArtistResult(
            seed_user_id=seed_user_id,
            candidate_count=candidate_count,
            evidence_count=evidence_count,
        )

    def _followed_quality_scores(self, followed_artist_ids: set[int] | list[int]) -> dict[int, float]:
        scores: dict[int, float] = {}
        for artist_id in followed_artist_ids:
            illusts = self.repository.fetch_illusts_for_artist(artist_user_id=int(artist_id))
            if not illusts:
                scores[int(artist_id)] = 0.0
                continue
            max_bm = max(int(i.total_bookmarks or 0) for i in illusts)
            # log-scale so mega-popular artists do not fully dominate seed picks.
            scores[int(artist_id)] = float(max_bm)
        return scores

    def _accept_user_candidate(
        self,
        *,
        user: object,
        followed_artist_ids: set[int],
        hydrated_artist_cache: dict[int, Artist],
        evidence_rows: list[tuple[int, str, str, float, str]],
        source_type: str,
        source_key: str,
        weight: float,
        detail: str,
        also_skip_user_id: int | None = None,
    ) -> bool:
        user_id = int(getattr(user, 'user_id', 0) or 0)
        if user_id <= 0 or user_id in followed_artist_ids:
            return False
        if also_skip_user_id is not None and user_id == also_skip_user_id:
            return False
        hydrated_artist_cache[user_id] = Artist(
            user_id=user_id,
            name=str(getattr(user, 'name', '') or f'artist-{user_id}'),
            account=str(getattr(user, 'account', '') or ''),
            profile_image_url=str(getattr(user, 'profile_image_url', '') or ''),
            is_followed=False,
        )
        evidence_rows.append((user_id, source_type, source_key, weight, detail))
        return True

    def _select_seed_artists_for_following_expand(
        self,
        *,
        pool_ids: list[int],
        seed_user_id: int,
        max_artists: int,
        sample_mode: str,
        sample_salt: int | str | None = None,
        explore_ratio: float = 0.25,
    ) -> list[int]:
        """Pick which followed artists' public following lists to expand.

        Modes:
        - quality_first: prefer high local max-bookmarks, keep explore slice.
        - random (default): true random each run.
        - hydrated_first: prefer artists that already have local illusts, then random fill.
        - hash: deterministic pseudo-random subset (stable across runs for same seed_user).
        - first: lowest user_id first (simple / legacy-like).
        """
        if max_artists <= 0 or not pool_ids:
            return []
        mode = (sample_mode or 'random').strip().lower()
        if mode not in {'random', 'hydrated_first', 'hash', 'first', 'quality_first', 'quality'}:
            mode = 'random'

        if mode == 'first':
            return sorted(pool_ids)[:max_artists]

        if mode == 'hash':
            return hash_sample_ids(
                pool_ids,
                seed_user_id=seed_user_id,
                limit=max_artists,
                sample_salt=sample_salt,
            )

        if mode in {'quality_first', 'quality'}:
            scores = self._followed_quality_scores(pool_ids)
            return sample_ids(
                pool_ids,
                seed_user_id=seed_user_id,
                limit=max_artists,
                mode='quality_first',
                quality_scores=scores,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )

        if mode == 'random':
            return sample_ids(pool_ids, seed_user_id=seed_user_id, limit=max_artists, mode='random')

        # hydrated_first
        with_illusts: list[int] = []
        without_illusts: list[int] = []
        for artist_id in pool_ids:
            illust_ids = self.repository.list_illust_ids_for_artist(artist_user_id=artist_id)
            if illust_ids:
                with_illusts.append(artist_id)
            else:
                without_illusts.append(artist_id)

        # Prefer hydrated; within each bucket use random for variety across runs.
        ordered = sample_ids(with_illusts, seed_user_id=seed_user_id, limit=len(with_illusts), mode='random')
        if len(ordered) < max_artists:
            ordered.extend(
                sample_ids(
                    without_illusts,
                    seed_user_id=seed_user_id,
                    limit=max_artists - len(ordered),
                    mode='random',
                )
            )
        return ordered[:max_artists]

    @staticmethod
    def _hash_sample(ids: list[int], *, seed_user_id: int, limit: int) -> list[int]:
        return hash_sample_ids(ids, seed_user_id=seed_user_id, limit=limit)
