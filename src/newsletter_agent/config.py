"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    model: str = "claude-haiku-4-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_articles_per_batch: int = 100

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class EmailConfig(BaseModel):
    enabled: bool = True
    from_address: str = "digest@yourdomain.com"
    to_addresses: list[str] = Field(default_factory=list)
    api_key_env: str = "RESEND_API_KEY"

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class SourceToggle(BaseModel):
    enabled: bool = True


class HackerNewsConfig(SourceToggle):
    min_score: int = 50
    max_stories: int = 100


class ArxivConfig(SourceToggle):
    categories: list[str] = Field(default_factory=lambda: ["cs.CR", "cs.AI", "cs.LG"])
    max_results: int = 50


class SourcesConfig(BaseModel):
    rss: SourceToggle = SourceToggle()
    arxiv: ArxivConfig = ArxivConfig()
    hackernews: HackerNewsConfig = HackerNewsConfig()
    github_trending: SourceToggle = SourceToggle()
    reddit: SourceToggle = SourceToggle()
    hackerone: SourceToggle = SourceToggle(enabled=False)
    oss_security: SourceToggle = SourceToggle()
    conferences: SourceToggle = SourceToggle(enabled=False)
    web: SourceToggle = SourceToggle()


class HealthConfig(BaseModel):
    max_consecutive_failures: int = 3
    auto_disable: bool = True
    retry_after_hours: int = 24


class DedupConfig(BaseModel):
    fuzzy_url: bool = True
    title_similarity_threshold: float = 0.85
    strip_query_params: list[str] = Field(default_factory=lambda: [
        "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
        "ref", "source", "fbclid", "gclid",
    ])


class ScheduleConfig(BaseModel):
    time: str = "08:00"
    timezone: str = "America/New_York"


class AppConfig(BaseModel):
    about_me: str = "AboutMe.md"
    interests: list[str] = Field(default_factory=lambda: [
        "web security",
        "vulnerability research",
        "LLM security",
        "AI agents",
        "exploit development",
    ])
    sources: SourcesConfig = SourcesConfig()
    llm: LLMConfig = LLMConfig()
    email: EmailConfig = EmailConfig()
    health: HealthConfig = HealthConfig()
    dedup: DedupConfig = DedupConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    state_dir: str = "data"
    lookback_hours: int = 24


def load_config(path: str | Path) -> AppConfig:
    """Load config from a YAML file, falling back to defaults for missing fields."""
    path = Path(path)
    if not path.exists():
        return AppConfig()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def load_about_me(path: str | Path) -> str:
    """Load the AboutMe.md user profile. Returns empty string if not found."""
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text().strip()
