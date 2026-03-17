from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..domain.models import RecommendationRun
from ..storage.repositories import RecommendationRepository
from ..utils.time_utils import iso_utc_now
from ..services.ports import CandidateRetriever, IngestService, ProfileService, RankService


@dataclass(slots=True)
class RecommendationRequest:
    seed_user_id: int
    refresh_token_ref: str
    max_results: int = 20
    persist_run: bool = True


class RecommendationPipeline:
    def __init__(
        self,
        repository: RecommendationRepository,
        ingest_service: IngestService,
        profile_service: ProfileService,
        candidate_retriever: CandidateRetriever,
        rank_service: RankService,
    ) -> None:
        self.repository = repository
        self.ingest_service = ingest_service
        self.profile_service = profile_service
        self.candidate_retriever = candidate_retriever
        self.rank_service = rank_service

    def run(self, request: RecommendationRequest) -> RecommendationRun:
        context = self.ingest_service.build_user_context(request.seed_user_id, request.refresh_token_ref)
        profile = self.profile_service.build_profile(context)
        candidates = self.candidate_retriever.retrieve(context, profile, limit=max(request.max_results * 2, request.max_results))
        items = list(self.rank_service.rank(context, profile, candidates, limit=request.max_results))
        run = RecommendationRun(
            seed_user_id=request.seed_user_id,
            run_id=f"run-{uuid4().hex[:12]}",
            mode="dry-run",
            items=items,
        )
        if request.persist_run:
            self.repository.record_run(run)
        return run
