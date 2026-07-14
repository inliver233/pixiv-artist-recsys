from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(slots=True, frozen=True)
class ProgressEvent:
    """Lightweight progress signal for long-running pipeline stages.

    stage: logical stage name (following_sync, hydrate_followed, ...)
    event: start | progress | done | info
    current / total: optional counters for bars (total may be 0/unknown)
    message: short human text
    meta: extra structured fields (pages, synced_count, artist_id, ...)
    """

    stage: str
    event: str
    current: int = 0
    total: int = 0
    message: str = ''
    meta: Mapping[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]


def emit(
    on_progress: ProgressCallback | None,
    *,
    stage: str,
    event: str,
    current: int = 0,
    total: int = 0,
    message: str = '',
    **meta: Any,
) -> None:
    if on_progress is None:
        return
    on_progress(
        ProgressEvent(
            stage=stage,
            event=event,
            current=current,
            total=total,
            message=message,
            meta=meta,
        )
    )
