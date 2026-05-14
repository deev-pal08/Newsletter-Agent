"""Source registry and plugin discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from newsletter_agent.sources.arxiv import ArxivSource
from newsletter_agent.sources.base import BaseSource
from newsletter_agent.sources.conferences import ConferencesSource
from newsletter_agent.sources.github_trending import GitHubTrendingSource
from newsletter_agent.sources.hackernews import HackerNewsSource
from newsletter_agent.sources.hackerone import HackerOneSource
from newsletter_agent.sources.oss_security import OSSSecuritySource
from newsletter_agent.sources.reddit import RedditSource
from newsletter_agent.sources.rss import RSSSource

if TYPE_CHECKING:
    from newsletter_agent.config import AppConfig

__all__ = [
    "BaseSource",
    "SOURCE_REGISTRY",
    "get_enabled_sources",
    "instantiate_source",
]

SOURCE_REGISTRY: dict[str, type[BaseSource]] = {
    "rss": RSSSource,
    "arxiv": ArxivSource,
    "hackernews": HackerNewsSource,
    "github_trending": GitHubTrendingSource,
    "reddit": RedditSource,
    "hackerone": HackerOneSource,
    "oss_security": OSSSecuritySource,
    "conferences": ConferencesSource,
}


def instantiate_source(source_id: str, config: AppConfig) -> BaseSource:
    """Create a source instance with proper config-driven arguments."""
    if source_id == "rss":
        return RSSSource(feeds=config.rss_feeds)
    if source_id == "arxiv":
        return ArxivSource(
            categories=config.sources.arxiv.categories,
            max_results=config.sources.arxiv.max_results,
        )
    if source_id == "hackernews":
        return HackerNewsSource(
            min_score=config.sources.hackernews.min_score,
            max_stories=config.sources.hackernews.max_stories,
        )
    if source_id == "reddit":
        return RedditSource(subreddits=config.reddit_subreddits)
    if source_id not in SOURCE_REGISTRY:
        raise ValueError(f"Unknown source: {source_id}")
    return SOURCE_REGISTRY[source_id]()


def is_source_enabled(source_id: str, config: AppConfig) -> bool:
    """Check if a source is enabled in config."""
    toggle = getattr(config.sources, source_id, None)
    return toggle.enabled if toggle else False


def get_enabled_sources(config: AppConfig) -> list[BaseSource]:
    """Instantiate sources that are enabled in config."""
    sources = [
        instantiate_source(sid, config)
        for sid in SOURCE_REGISTRY
        if is_source_enabled(sid, config)
    ]
    return [s for s in sources if s.is_available()]
