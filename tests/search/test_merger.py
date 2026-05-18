"""Tests for URL merger and deduplication."""

from __future__ import annotations

from newsletter_agent.search.merger import merge_and_deduplicate, normalize_search_url
from newsletter_agent.search.models import LayerResult, SearchResult


def _result(url: str, layer: str = "tavily", content: str | None = None) -> SearchResult:
    return SearchResult(
        url=url,
        title=f"Title for {url}",
        description="desc",
        source_layer=layer,
        source_query="test query",
        query_category="CORE",
        full_content=content,
    )


def _layer(name: str, results: list[SearchResult]) -> LayerResult:
    return LayerResult(
        layer_name=name,
        results=results,
        query_count=1,
        success=True,
    )


def test_exact_duplicate_urls_removed():
    layers = [
        _layer("Tavily", [_result("https://example.com/article")]),
        _layer("Exa", [_result("https://example.com/article", "exa")]),
    ]
    merged = merge_and_deduplicate(layers)
    assert len(merged) == 1


def test_url_normalization_trailing_slash():
    assert normalize_search_url("https://example.com/") == normalize_search_url("https://example.com")


def test_url_normalization_utm_params():
    clean = normalize_search_url("https://example.com/article")
    with_utm = normalize_search_url("https://example.com/article?utm_source=twitter&utm_medium=social")
    assert clean == with_utm


def test_url_normalization_www_prefix():
    assert normalize_search_url("https://www.example.com/page") == normalize_search_url("https://example.com/page")


def test_high_confidence_flag():
    layers = [
        _layer("Tavily", [_result("https://example.com/hot")]),
        _layer("Exa", [_result("https://example.com/hot", "exa")]),
        _layer("Perplexity Deep", [_result("https://example.com/hot", "perplexity")]),
    ]
    merged = merge_and_deduplicate(layers)
    assert len(merged) == 1
    assert merged[0].high_confidence is True


def test_high_confidence_sorted_first():
    layers = [
        _layer("Tavily", [
            _result("https://example.com/only-tavily"),
            _result("https://example.com/multi"),
        ]),
        _layer("Exa", [_result("https://example.com/multi", "exa")]),
        _layer("Perplexity Deep", [_result("https://example.com/multi", "perplexity")]),
    ]
    merged = merge_and_deduplicate(layers)
    assert len(merged) == 2
    assert merged[0].high_confidence is True
    assert merged[1].high_confidence is False


def test_found_by_layers_tracked():
    layers = [
        _layer("Tavily", [_result("https://example.com/shared")]),
        _layer("Exa", [_result("https://example.com/shared", "exa")]),
    ]
    merged = merge_and_deduplicate(layers)
    assert len(merged) == 1
    assert set(merged[0].found_by_layers) == {"Tavily", "Exa"}


def test_prefers_result_with_full_content():
    layers = [
        _layer("Tavily", [_result("https://example.com/doc")]),
        _layer("Exa", [_result("https://example.com/doc", "exa", content="full text here")]),
    ]
    merged = merge_and_deduplicate(layers)
    assert len(merged) == 1
    assert merged[0].full_content == "full text here"
