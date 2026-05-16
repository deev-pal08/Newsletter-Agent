"""Source registry and plugin discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from newsletter_agent.sources.base import BaseSource
from newsletter_agent.sources.reddit import RedditSource
from newsletter_agent.sources.rss import RSSSource
from newsletter_agent.sources.web import WebSource

if TYPE_CHECKING:
    from newsletter_agent.config import AppConfig
    from newsletter_agent.state.store import StateStore

__all__ = [
    "BaseSource",
    "SOURCE_REGISTRY",
    "get_enabled_sources",
    "instantiate_source",
    "is_source_enabled",
]

SOURCE_REGISTRY: dict[str, type[BaseSource]] = {
    "rss": RSSSource,
    "reddit": RedditSource,
    "web": WebSource,
}


def instantiate_source(
    source_id: str,
    config: AppConfig,
    state: StateStore | None = None,
) -> BaseSource:
    """Create a source instance with proper config-driven arguments."""
    if source_id == "rss":
        feeds = state.get_rss_feeds() if state else {}
        return RSSSource(feeds=feeds)
    if source_id == "reddit":
        subreddits = state.get_subreddits() if state else []
        return RedditSource(subreddits=subreddits)
    if source_id == "web":
        pages = state.get_web_pages() if state else {}
        try:
            api_key = config.llm.api_key
        except ValueError:
            api_key = None
        return WebSource(
            pages=pages,
            api_key=api_key,
            jina_enabled=config.extraction.jina_enabled,
            firecrawl_enabled=config.extraction.firecrawl_enabled,
            haiku_fallback_enabled=config.extraction.haiku_fallback_enabled,
        )
    if source_id not in SOURCE_REGISTRY:
        raise ValueError(f"Unknown source: {source_id}")
    return SOURCE_REGISTRY[source_id]()


def is_source_enabled(source_id: str, config: AppConfig) -> bool:
    """Check if a source is enabled in config."""
    toggle = getattr(config.sources, source_id, None)
    return toggle.enabled if toggle else False


def get_enabled_sources(
    config: AppConfig,
    state: StateStore | None = None,
) -> list[BaseSource]:
    """Instantiate sources that are enabled in config."""
    sources = [
        instantiate_source(sid, config, state)
        for sid in SOURCE_REGISTRY
        if is_source_enabled(sid, config)
    ]
    return [s for s in sources if s.is_available()]
