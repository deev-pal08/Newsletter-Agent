"""Tests for query generator."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from newsletter_agent.search.models import QueryPlan
from newsletter_agent.search.query_generator import _build_fallback, generate_queries


def _mock_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.text = content
    response = MagicMock()
    response.content = [msg]
    return response


def _make_query_json(num: int = 20) -> str:
    categories = (
        ["CORE"] * 4 + ["DEPTH"] * 4 + ["FORMAT"] * 3
        + ["RESEARCHER"] * 3 + ["EMERGING"] * 3 + ["OBSCURE"] * 3
    )
    queries = []
    for i in range(num):
        cat = categories[i] if i < len(categories) else "CORE"
        queries.append({
            "id": f"q{i+1:02d}",
            "category": cat,
            "query": f"test query {i+1}",
            "rationale": f"reason {i+1}",
        })
    return json.dumps({"topic": "test", "queries": queries})


def test_generates_20_queries():
    client = MagicMock()
    client.messages.create.return_value = _mock_response(_make_query_json(20))
    plan = generate_queries("AI security", "I am a researcher", client)
    assert len(plan.queries) == 20
    assert plan.topic == "AI security"


def test_all_categories_present():
    client = MagicMock()
    client.messages.create.return_value = _mock_response(_make_query_json(20))
    plan = generate_queries("AI security", "I am a researcher", client)
    categories = {q.category for q in plan.queries}
    assert categories == {"CORE", "DEPTH", "FORMAT", "RESEARCHER", "EMERGING", "OBSCURE"}


def test_fallback_on_parse_failure():
    client = MagicMock()
    client.messages.create.return_value = _mock_response("not valid json at all")
    plan = generate_queries("AI security", "about me", client)
    assert len(plan.queries) == len(_build_fallback("AI security"))


def test_queries_contain_topic():
    client = MagicMock()
    client.messages.create.return_value = _mock_response(_make_query_json(20))
    plan = generate_queries("web security vulnerabilities", "researcher", client)
    assert plan.topic == "web security vulnerabilities"
    assert isinstance(plan, QueryPlan)
