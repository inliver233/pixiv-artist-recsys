from __future__ import annotations

from ..domain.models import Artist, CandidateEvidence, RecommendationItem
from .ports import CandidateArtist, CandidateRetriever, IngestService, ProfileService, RankService, TasteProfile, UserContext


class DryRunIngestService(IngestService):
    def build_user_context(self, seed_user_id: int, refresh_token_ref: str) -> UserContext:
        return UserContext(seed_user_id=seed_user_id, refresh_token_ref=refresh_token_ref)


class DryRunProfileService(ProfileService):
    def build_profile(self, context: UserContext) -> TasteProfile:
        return TasteProfile(top_tags=["dry-run", "pixiv"], negative_tags=[])


class DryRunCandidateRetriever(CandidateRetriever):
    def retrieve(self, context: UserContext, profile: TasteProfile, limit: int):
        artist = Artist(user_id=900000 + context.seed_user_id, name="dry-run-artist", account="dryrun")
        evidence = [CandidateEvidence(source_type="dry-run", source_key="bootstrap", weight=1.0, detail=",".join(profile.top_tags))]
        return [CandidateArtist(artist=artist, evidence=evidence)][:limit]


class DryRunRankService(RankService):
    def rank(self, context: UserContext, profile: TasteProfile, candidates, limit: int):
        results: list[RecommendationItem] = []
        for idx, candidate in enumerate(candidates[:limit], start=1):
            results.append(
                RecommendationItem(
                    artist=candidate.artist,
                    score=max(0.0, 1.0 - (idx - 1) * 0.01),
                    confidence=0.5,
                    reasons=[f"dry-run candidate from {candidate.evidence[0].source_type}"],
                    evidence=list(candidate.evidence),
                )
            )
        return results
