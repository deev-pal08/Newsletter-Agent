"""HackerOne disclosed reports via GraphQL API (experimental)."""

from __future__ import annotations

import contextlib
from datetime import datetime

import httpx

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

HACKERONE_GRAPHQL = "https://hackerone.com/graphql"

HACKTIVITY_QUERY = """
query {
  hacktivity_items(first: 25, order_by: {field: popular, direction: DESC}) {
    edges {
      node {
        ... on Disclosed {
          id
          reporter { username }
          team { handle, name }
          report {
            title
            url
            severity_rating
            disclosed_at
            substate
          }
        }
      }
    }
  }
}
"""


class HackerOneSource(BaseSource):
    @property
    def name(self) -> str:
        return "HackerOne"

    @property
    def source_id(self) -> str:
        return "hackerone"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    HACKERONE_GRAPHQL,
                    json={"query": HACKTIVITY_QUERY},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, Exception):
                return []

        articles: list[Article] = []
        edges = data.get("data", {}).get("hacktivity_items", {}).get("edges", [])
        for edge in edges:
            node = edge.get("node", {})
            report = node.get("report", {})
            if not report:
                continue
            title = report.get("title", "Untitled")
            url = report.get("url", "")
            if not url:
                continue

            disclosed_at = None
            if report.get("disclosed_at"):
                with contextlib.suppress(ValueError, TypeError):
                    disclosed_at = datetime.fromisoformat(report["disclosed_at"])
            if since and disclosed_at and disclosed_at < since:
                continue

            team = node.get("team", {})
            severity = report.get("severity_rating", "none")

            articles.append(Article(
                title=title,
                url=url,
                source_id=self.source_id,
                source_name=self.name,
                published_at=disclosed_at,
                raw_summary=f"Severity: {severity} | Program: {team.get('name', 'Unknown')}",
                tags=[severity],
                extra={
                    "program": team.get("handle", ""),
                    "severity": severity,
                    "reporter": node.get("reporter", {}).get("username", ""),
                },
            ))
        return articles
