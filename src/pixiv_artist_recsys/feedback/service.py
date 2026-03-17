from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..storage.repositories import RecommendationRepository

VALID_FEEDBACK_ACTIONS = {'follow', 'dislike', 'block'}


@dataclass(slots=True)
class NegativeProfileSummary:
    seed_user_id: int
    negative_tags: list[tuple[str, float]]
    disliked_artist_ids: list[int]
    blocked_artist_ids: list[int]
    event_count: int


class FeedbackService:
    def __init__(self, *, repository: RecommendationRepository) -> None:
        self.repository = repository

    @staticmethod
    def normalize_tag(tag: str) -> str:
        return str(tag or '').strip().lower().replace(' ', '_')

    def record_feedback(
        self,
        *,
        seed_user_id: int,
        artist_user_id: int,
        action: str,
        source_run_id: str = '',
        note: str = '',
        top_n_tags: int = 20,
    ) -> NegativeProfileSummary:
        action = str(action or '').strip().lower()
        if action not in VALID_FEEDBACK_ACTIONS:
            raise ValueError(f'Unsupported feedback action: {action}')
        self.repository.record_feedback_event(
            seed_user_id=seed_user_id,
            artist_user_id=artist_user_id,
            action=action,
            source_run_id=source_run_id,
            note=note,
        )
        return self.build_negative_profile(seed_user_id=seed_user_id, top_n_tags=top_n_tags)

    def build_negative_profile(self, *, seed_user_id: int, top_n_tags: int = 20) -> NegativeProfileSummary:
        events = self.repository.fetch_feedback_events(seed_user_id=seed_user_id)
        negative_counter: Counter[str] = Counter()
        disliked_artist_ids: list[int] = []
        blocked_artist_ids: list[int] = []

        for artist_user_id, _, action, _, _, _ in events:
            if action not in {'dislike', 'block'}:
                continue
            if action == 'dislike':
                disliked_artist_ids.append(artist_user_id)
                weight = 1.0
            else:
                blocked_artist_ids.append(artist_user_id)
                weight = 2.0
            normalized_tags = sorted({
                self.normalize_tag(tag)
                for tag in self.repository.fetch_artist_tags(artist_user_id=artist_user_id)
                if self.normalize_tag(tag)
            })
            for tag in normalized_tags:
                negative_counter[tag] += weight

        total = sum(negative_counter.values()) or 1
        negative_tags = [(tag, weight / total) for tag, weight in negative_counter.most_common(top_n_tags)]
        self.repository.replace_user_negative_profile(seed_user_id=seed_user_id, weights=negative_tags)
        return NegativeProfileSummary(
            seed_user_id=seed_user_id,
            negative_tags=negative_tags,
            disliked_artist_ids=sorted(set(disliked_artist_ids)),
            blocked_artist_ids=sorted(set(blocked_artist_ids)),
            event_count=len(events),
        )
