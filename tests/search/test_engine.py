"""Tests for the DeepSearchEngine orchestrator."""

from __future__ import annotations

from unittest.mock import patch

from newsletter_agent.search.engine import DeepSearchEngine
from newsletter_agent.search.models import LayerResult, SearchQuery, SearchResult


def _mock_layer_result(name: str, count: int = 5) -> LayerResult:
    results = [
        SearchResult(
            url=f"https://example.com/{name.lower()}/{i}",
            title=f"{name} result {i}",
            description="description",
            source_layer=name.lower(),
            source_query="test query",
            query_category="CORE",
        )
        for i in range(count)
    ]
    return LayerResult(
        layer_name=name,
        results=results,
        query_count=20,
        success=True,
        duration_seconds=1.0,
    )


def _make_engine() -> DeepSearchEngine:
    from newsletter_agent.config import SearchConfig
    config = SearchConfig()
    # Disable all layers (we'll mock _run_layers)
    config.tavily.enabled = False
    config.exa.enabled = False
    config.perplexity.enabled = False

    engine = DeepSearchEngine(config=config, anthropic_api_key="test-key")
    return engine


def _mock_query_plan():
    from datetime import UTC, datetime

    from newsletter_agent.search.models import QueryPlan
    return QueryPlan(
        topic="test",
        queries=[SearchQuery("q01", "CORE", "test", "test")],
        generated_at=datetime.now(UTC),
    )


def test_all_layers_called():
    engine = _make_engine()

    mock_results = [
        _mock_layer_result("Tavily"),
        _mock_layer_result("Exa"),
        _mock_layer_result("Perplexity Deep"),
    ]

    with (
        patch.object(engine, "_run_layers", return_value=mock_results),
        patch("newsletter_agent.search.engine.generate_queries") as mock_gen,
    ):
        mock_gen.return_value = _mock_query_plan()
        result = engine.run("AI security", "researcher")

    assert len(result.layer_results) == 3
    assert result.total_urls_found == 15


def test_layer_failure_does_not_crash_engine():
    engine = _make_engine()

    mock_results = [
        _mock_layer_result("Tavily"),
        _mock_layer_result("Exa"),
        LayerResult(
            layer_name="Perplexity Deep",
            results=[],
            query_count=0,
            success=False,
            error="RuntimeError: crash",
        ),
    ]

    with (
        patch.object(engine, "_run_layers", return_value=mock_results),
        patch("newsletter_agent.search.engine.generate_queries") as mock_gen,
    ):
        mock_gen.return_value = _mock_query_plan()
        result = engine.run("test topic", "about me")

    assert result is not None
    assert result.unique_urls == 10  # only tavily + exa results


def test_cost_estimate_calculated():
    engine = _make_engine()

    mock_results = [_mock_layer_result("Tavily")]

    with (
        patch.object(engine, "_run_layers", return_value=mock_results),
        patch("newsletter_agent.search.engine.generate_queries") as mock_gen,
    ):
        mock_gen.return_value = _mock_query_plan()
        result = engine.run("test", "about")

    assert result.cost_estimate_usd > 0


def test_merged_results_in_output():
    engine = _make_engine()

    mock_results = [
        _mock_layer_result("Tavily", count=3),
        _mock_layer_result("Exa", count=2),
    ]

    with (
        patch.object(engine, "_run_layers", return_value=mock_results),
        patch("newsletter_agent.search.engine.generate_queries") as mock_gen,
    ):
        mock_gen.return_value = _mock_query_plan()
        result = engine.run("test", "about")

    assert len(result.merged_results) > 0
    assert result.unique_urls == len(result.merged_results)
