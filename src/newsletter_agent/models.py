"""Core data models shared across all modules."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from newsletter_agent.utils import normalize_url, title_fingerprint


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
        return hashlib.sha256(self.normalized_url.encode()).hexdigest()[:16]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def normalized_url(self) -> str:
        return normalize_url(self.url)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def title_fp(self) -> str:
        return title_fingerprint(self.title)


class SourceHealth(BaseModel):
    """Health status of a data source."""

    source_id: str
    last_fetch: datetime | None = None
    last_success: datetime | None = None
    consecutive_errors: int = 0
    total_articles_fetched: int = 0
    last_error: str | None = None
    auto_disabled: bool = False


class Digest(BaseModel):
    """A complete digest ready for delivery."""

    digest_id: int | None = None
    date: datetime
    articles: list[Article]
    sources_used: list[str]
    total_fetched: int
    total_after_dedup: int
    generation_time_seconds: float
    email_sent: bool = False
    email_id: str | None = None

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
