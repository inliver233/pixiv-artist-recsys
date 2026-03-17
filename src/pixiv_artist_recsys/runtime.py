from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppSettings


@dataclass(slots=True)
class RuntimeContext:
    settings: AppSettings

    @property
    def db_path(self) -> Path:
        return self.settings.storage.sqlite_path

    def prepare(self) -> None:
        self.settings.ensure_directories()
