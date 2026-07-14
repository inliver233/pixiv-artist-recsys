from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..domain.models import Artist, SeedUser
from ..storage.repositories import RecommendationRepository


_ID_RE = re.compile(r'(?<!\d)(\d{3,12})(?!\d)')


@dataclass(slots=True)
class FollowingFileImportResult:
    seed_user_id: int
    path: str
    lines_read: int
    ids_parsed: int
    unique_ids: int
    edges_before: int
    edges_after: int
    artists_upserted: int
    edges_added: int


class FollowingFileImportService:
    """Import a local following export (one UID per line, or mixed text with IDs)."""

    def __init__(self, *, repository: RecommendationRepository) -> None:
        self.repository = repository

    def import_file(
        self,
        *,
        seed_user_id: int,
        path: str | Path,
        refresh_token_ref: str = 'import:following-file',
    ) -> FollowingFileImportResult:
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f'following file not found: {file_path}')

        existing = self.repository.fetch_seed_user(user_id=seed_user_id)
        self.repository.upsert_seed_user(
            SeedUser(
                user_id=seed_user_id,
                refresh_token_ref=existing.refresh_token_ref if existing is not None else refresh_token_ref,
                allow_ai=existing.allow_ai if existing is not None else False,
                allow_r18=existing.allow_r18 if existing is not None else False,
            )
        )

        before_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        lines = file_path.read_text(encoding='utf-8-sig').splitlines()
        parsed: list[int] = []
        for line in lines:
            text = line.strip()
            if not text or text.startswith('#'):
                continue
            # Prefer whole-line integer; else extract first plausible id.
            if text.isdigit():
                value = int(text)
                if value > 0:
                    parsed.append(value)
                continue
            match = _ID_RE.search(text)
            if match:
                value = int(match.group(1))
                if value > 0:
                    parsed.append(value)

        unique_ids = sorted(set(parsed))
        artists_upserted = 0
        for artist_user_id in unique_ids:
            existing_artist = self.repository.fetch_artist(artist_user_id=artist_user_id)
            if existing_artist is None:
                self.repository.upsert_artist(
                    Artist(
                        user_id=artist_user_id,
                        name=f'artist-{artist_user_id}',
                        is_followed=True,
                    )
                )
            else:
                self.repository.upsert_artist(
                    Artist(
                        user_id=artist_user_id,
                        name=existing_artist.name or f'artist-{artist_user_id}',
                        account=existing_artist.account,
                        is_followed=True,
                        profile_image_url=existing_artist.profile_image_url,
                    )
                )
            artists_upserted += 1
            self.repository.upsert_following_edge(seed_user_id=seed_user_id, artist_user_id=artist_user_id)

        after_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        return FollowingFileImportResult(
            seed_user_id=seed_user_id,
            path=str(file_path),
            lines_read=len(lines),
            ids_parsed=len(parsed),
            unique_ids=len(unique_ids),
            edges_before=len(before_ids),
            edges_after=len(after_ids),
            artists_upserted=artists_upserted,
            edges_added=max(0, len(after_ids) - len(before_ids)),
        )
