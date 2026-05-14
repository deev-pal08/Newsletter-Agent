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

__all__ = ["BaseSource", "SOURCE_REGISTRY", "get_enabled_sources"]

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


def get_enabled_sources(config: AppConfig) -> list[BaseSource]:
    """Instantiate sources that are enabled in config."""
    sources: list[BaseSource] = []

    if config.sources.rss.enabled:
        sources.append(RSSSource(feeds=config.rss_feeds))
    if config.sources.arxiv.enabled:
        sources.append(ArxivSource(
            categories=config.sources.arxiv.categories,
            max_results=config.sources.arxiv.max_results,
        ))
    if config.sources.hackernews.enabled:
        sources.append(HackerNewsSource(
            min_score=config.sources.hackernews.min_score,
            max_stories=config.sources.hackernews.max_stories,
        ))
    if config.sources.github_trending.enabled:
        sources.append(GitHubTrendingSource())
    if config.sources.reddit.enabled:
        sources.append(RedditSource(subreddits=config.reddit_subreddits))
    if config.sources.hackerone.enabled:
        sources.append(HackerOneSource())
    if config.sources.oss_security.enabled:
        sources.append(OSSSecuritySource())
    if config.sources.conferences.enabled:
        sources.append(ConferencesSource())

    return [s for s in sources if s.is_available()]
