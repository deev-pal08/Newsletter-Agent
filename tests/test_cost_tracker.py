"""Tests for cost tracker."""

from __future__ import annotations

import json

from newsletter_agent.cost_tracker import CostBreakdown


def test_initial_total_is_zero() -> None:
    cost = CostBreakdown()
    assert cost.total == 0.0


def test_add_filter() -> None:
    cost = CostBreakdown()
    cost.add_filter(100)
    assert cost.filtering_deepseek == 0.025


def test_add_ranking_sonnet_batch() -> None:
    cost = CostBreakdown()
    cost.add_ranking(100, "claude-sonnet-4-6", batch=True)
    assert cost.ranking_claude > 0
    # Batch should be half of sync
    sync_cost = CostBreakdown()
    sync_cost.add_ranking(100, "claude-sonnet-4-6", batch=False)
    assert cost.ranking_claude < sync_cost.ranking_claude


def test_total_accumulates() -> None:
    cost = CostBreakdown()
    cost.add_deep_search(0.50)
    cost.add_filter(50)
    cost.add_ranking(50, "claude-sonnet-4-6", batch=True)
    assert cost.total == cost.deep_search + cost.filtering_deepseek + cost.ranking_claude
    assert cost.deep_search == 0.50


def test_format_includes_total() -> None:
    cost = CostBreakdown()
    cost.add_deep_search(0.25)
    cost.add_ranking(10, "claude-haiku-4-5")
    output = cost.format()
    assert "Total (API):" in output
    assert "Deep Search Engine" in output


def test_to_dict() -> None:
    cost = CostBreakdown()
    cost.add_deep_search(0.35)
    d = cost.to_dict()
    assert "total_api_cost" in d
    assert "deep_search" in d
    assert d["deep_search"] == 0.35


def test_to_json() -> None:
    cost = CostBreakdown()
    cost.add_deep_search(0.42)
    j = cost.to_json()
    data = json.loads(j)
    assert "total_api_cost" in data
    assert data["deep_search"] == 0.42
