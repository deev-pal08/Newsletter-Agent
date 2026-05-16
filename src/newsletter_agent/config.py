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
    use_batch: bool = True
    prompt_caching: bool = True

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


class SourcesConfig(BaseModel):
    rss: SourceToggle = SourceToggle()
    reddit: SourceToggle = SourceToggle()
    web: SourceToggle = SourceToggle()


class HealthConfig(BaseModel):
    max_consecutive_failures: int = 3
    auto_disable: bool = True
    retry_after_hours: int = 24


class DedupConfig(BaseModel):
    strip_tracking_params: bool = True
    use_semantic: bool = True
    semantic_threshold: float = 0.88
    embedding_model: str = "text-embedding-3-small"
    cache_embeddings: bool = True


class DiscoveryConfig(BaseModel):
    tavily_queries_per_scan: int = 2
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    search_depth: str = "advanced"


class ExtractionConfig(BaseModel):
    jina_enabled: bool = True
    firecrawl_enabled: bool = False
    haiku_fallback_enabled: bool = True


class FilteringConfig(BaseModel):
    enabled: bool = True
    model: str = "deepseek-chat"
    fail_open: bool = True


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
    discovery: DiscoveryConfig = DiscoveryConfig()
    extraction: ExtractionConfig = ExtractionConfig()
    filtering: FilteringConfig = FilteringConfig()
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
