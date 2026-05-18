"""Deep Search Engine — 3-layer parallel search for comprehensive coverage."""

from newsletter_agent.search.engine import DeepSearchEngine
from newsletter_agent.search.models import (
    LayerResult,
    QueryPlan,
    SearchEngineResult,
    SearchQuery,
    SearchResult,
)

__all__ = [
    "DeepSearchEngine",
    "LayerResult",
    "QueryPlan",
    "SearchEngineResult",
    "SearchQuery",
    "SearchResult",
]
