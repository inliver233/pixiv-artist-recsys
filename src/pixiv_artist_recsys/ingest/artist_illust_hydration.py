from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Artist, Illust
from ..pixiv import PixivAppApiClient
from ..pixiv.models import PixivIllustSummary
from ..storage.repositories import RecommendationRepository
from ..utils.progress import ProgressCallback, emit
from ..utils.sampling import sample_ids


@dataclass(slots=True)
class ArtistIllustHydrationResult:
    seed_user_id: int
    artists_processed: int
    illusts_upserted: int
    scope: str = 'followed'
    detail_fetches: int = 0
    list_only_saves: int = 0


class ArtistIllustHydrationService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

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
        if max_artists is not None:
            # Prefer multi-source / higher-weight candidates when quality scores available.
            quality_scores = self._candidate_priority_scores(seed_user_id=seed_user_id, candidate_ids=candidate_ids)
            candidate_ids = sample_ids(
                candidate_ids,
                seed_user_id=seed_user_id,
                limit=max(0, int(max_artists)),
                mode=seed_sample,
                quality_scores=quality_scores,
                sample_salt=sample_salt,
                explore_ratio=explore_ratio,
            )
        return self._hydrate_artist_ids(
            seed_user_id=seed_user_id,
            artist_user_ids=candidate_ids,
            per_artist_limit=per_artist_limit,
            scope='candidate',
            on_progress=on_progress,
        )

    def _quality_scores(self, artist_ids: list[int]) -> dict[int, float]:
        scores: dict[int, float] = {}
        for artist_id in artist_ids:
            illusts = self.repository.fetch_illusts_for_artist(artist_user_id=int(artist_id))
            if not illusts:
                scores[int(artist_id)] = 0.0
                continue
            scores[int(artist_id)] = float(max(int(i.total_bookmarks or 0) for i in illusts))
        return scores

    def _candidate_priority_scores(self, *, seed_user_id: int, candidate_ids: list[int]) -> dict[int, float]:
        """Score candidates for hydrate sampling: evidence weight sum + local max bookmarks."""
        weight_sum: dict[int, float] = {int(cid): 0.0 for cid in candidate_ids}
        for candidate_user_id, _source_type, _source_key, weight, _detail in self.repository.fetch_artist_candidates(
            seed_user_id=seed_user_id
        ):
            cid = int(candidate_user_id)
            if cid in weight_sum:
                weight_sum[cid] += float(weight)
        scores: dict[int, float] = {}
        for cid in candidate_ids:
            illusts = self.repository.fetch_illusts_for_artist(artist_user_id=int(cid))
            max_bm = max((int(i.total_bookmarks or 0) for i in illusts), default=0)
            # Evidence first so multi-source unhydrated candidates still get hydrated.
            scores[int(cid)] = float(weight_sum.get(int(cid), 0.0)) * 1000.0 + float(max_bm)
        return scores

    def _hydrate_artist_ids(
        self,
        *,
        seed_user_id: int,
        artist_user_ids: list[int],
        per_artist_limit: int,
        scope: str,
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
        for index, artist_user_id in enumerate(artist_user_ids, start=1):
            page = self.pixiv_client.fetch_user_illusts(user_id=artist_user_id)
            artist_illusts = 0
            for summary in page.items[:per_artist_limit]:
                detail = None
                # user_illusts list payload usually already has tags + ai/r18 flags.
                # Skip illust/detail when tags are present → ~half the hydrate API volume.
                if summary.tags:
                    list_only_saves += 1
                    self._upsert_from_summary(summary)
                else:
                    detail = self.pixiv_client.fetch_illust_detail(illust_id=summary.illust_id)
                    detail_fetches += 1
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
            )
        )
        self.repository.replace_illust_tags(illust_id=summary.illust_id, tags=list(summary.tags or []))
