"""Shared data models for the deep search engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SearchQuery:
    id: str
    category: str  # CORE | DEPTH | FORMAT | RESEARCHER | THREAT | OBSCURE
    query: str
    rationale: str


@dataclass
class QueryPlan:
    topic: str
    queries: list[SearchQuery]
    generated_at: datetime


@dataclass
class SearchResult:
    url: str
    title: str
    description: str
    source_layer: str  # "tavily" | "exa" | "perplexity"
    source_query: str
    query_category: str  # CORE | DEPTH | FORMAT | RESEARCHER | EMERGING | OBSCURE
    published_date: str | None = None
    full_content: str | None = None
    score: float | None = None
    found_by_layers: list[str] = field(default_factory=list)
    high_confidence: bool = False


@dataclass
class LayerResult:
    layer_name: str
    results: list[SearchResult]
    query_count: int
    success: bool
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class SearchEngineResult:
    topic: str
    query_plan: QueryPlan
    layer_results: list[LayerResult]
    merged_results: list[SearchResult]
    total_urls_found: int
    unique_urls: int
    duration_seconds: float
    cost_estimate_usd: float
