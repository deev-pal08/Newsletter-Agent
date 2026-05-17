"""Tests for cost tracker."""

from __future__ import annotations

import json

from newsletter_agent.cost_tracker import CostBreakdown


def test_initial_total_is_zero() -> None:
    cost = CostBreakdown()
    assert cost.total == 0.0


def test_add_tavily_advanced() -> None:
    cost = CostBreakdown()
    cost.add_tavily(2, depth="advanced")
    assert cost.discovery_tavily_credits == 2 * 4


def test_add_tavily_basic() -> None:
    cost = CostBreakdown()
    cost.add_tavily(3, depth="basic")
    assert cost.discovery_tavily_credits == 3 * 1


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
    cost.add_tavily(2)
    cost.add_filter(50)
    cost.add_ranking(50, "claude-sonnet-4-6", batch=True)
    assert cost.total == cost.filtering_deepseek + cost.ranking_claude
    assert cost.discovery_tavily_credits == 8


def test_format_includes_total() -> None:
    cost = CostBreakdown()
    cost.add_tavily(1)
    cost.add_ranking(10, "claude-haiku-4-5")
    output = cost.format()
    assert "Total (API):" in output
    assert "credits" in output


def test_to_dict() -> None:
    cost = CostBreakdown()
    cost.add_tavily(1)
    d = cost.to_dict()
    assert "total_api_cost" in d
    assert "discovery_tavily_credits" in d
    assert d["discovery_tavily_credits"] == 4


def test_to_json() -> None:
    cost = CostBreakdown()
    cost.add_tavily(1)
    j = cost.to_json()
    data = json.loads(j)
    assert "total_api_cost" in data
    assert data["discovery_tavily_credits"] == 4
