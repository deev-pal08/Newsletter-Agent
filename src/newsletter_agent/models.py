"""Core data models shared across all modules."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class Priority(StrEnum):
    CRITICAL = "CRITICAL - ACT NOW"
    IMPORTANT = "IMPORTANT - READ THIS WEEK"
    INTERESTING = "INTERESTING - QUEUE FOR WEEKEND"
    REFERENCE = "REFERENCE - SAVE FOR LATER"


class Article(BaseModel):
    """A single item fetched from any source."""

    title: str
    url: str
    source_id: str
    source_name: str
    published_at: datetime | None = None
    raw_summary: str = ""
    ai_summary: str = ""
    priority: Priority | None = None
    tags: list[str] = Field(default_factory=list)
    score: int | None = None
    extra: dict[str, str] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


class Digest(BaseModel):
    """A complete digest ready for delivery."""

    date: datetime
    articles: list[Article]
    sources_used: list[str]
    total_fetched: int
    total_after_dedup: int
    generation_time_seconds: float

    @property
    def critical(self) -> list[Article]:
        return [a for a in self.articles if a.priority == Priority.CRITICAL]

    @property
    def important(self) -> list[Article]:
        return [a for a in self.articles if a.priority == Priority.IMPORTANT]

    @property
    def interesting(self) -> list[Article]:
        return [a for a in self.articles if a.priority == Priority.INTERESTING]

    @property
    def reference(self) -> list[Article]:
        return [a for a in self.articles if a.priority == Priority.REFERENCE]
