from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ..domain.models import Artist, CandidateEvidence, RecommendationItem


@dataclass(slots=True)
class UserContext:
    seed_user_id: int
    refresh_token_ref: str
    allow_ai: bool = False
    allow_r18: bool = False


@dataclass(slots=True)
class TasteProfile:
    top_tags: list[str]
    negative_tags: list[str]


@dataclass(slots=True)
class CandidateArtist:
    artist: Artist
    evidence: list[CandidateEvidence]


class IngestService(Protocol):
    def build_user_context(self, seed_user_id: int, refresh_token_ref: str) -> UserContext: ...


class ProfileService(Protocol):
    def build_profile(self, context: UserContext) -> TasteProfile: ...


class CandidateRetriever(Protocol):
    def retrieve(self, context: UserContext, profile: TasteProfile, limit: int) -> Sequence[CandidateArtist]: ...


class RankService(Protocol):
    def rank(self, context: UserContext, profile: TasteProfile, candidates: Sequence[CandidateArtist], limit: int) -> Sequence[RecommendationItem]: ...
