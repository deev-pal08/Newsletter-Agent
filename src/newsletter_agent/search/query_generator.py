"""Query generation — Claude Sonnet expands topics into 20 targeted search queries."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import anthropic

from newsletter_agent.search.models import QueryPlan, SearchQuery

logger = logging.getLogger(__name__)

QUERY_GEN_PROMPT = """\
You are a search query strategist for an intelligence newsletter agent.

User profile:
{about_me}

Research topic: {topic}

Generate exactly 20 search queries that together provide exhaustive coverage \
of this topic. The queries must cover ALL of these angles:

1. CORE queries (4 queries) — broad topic coverage, recent news and developments
2. DEPTH queries (4 queries) — site-specific deep dives:
   - Target authoritative platforms for this topic (e.g., GitHub, arXiv, \
official databases, industry-specific repositories)
   - Target specialized directories or registries relevant to the domain
   - Target official standards bodies, regulatory sites, or governing organizations
   - Target niche domain-specific resources that experts in this field would use
3. FORMAT queries (3 queries) — find specific content formats:
   - Research reports, whitepapers, and PDF publications
   - Official advisories, announcements, and disclosures
   - Technical writeups, case studies, and post-mortems
4. RESEARCHER queries (3 queries) — find content from individual experts:
   - Personal blogs and independent analysis
   - Conference talks and presentation writeups
   - Practitioner writeups and field reports
5. EMERGING queries (3 queries) — cutting-edge and forward-looking:
   - Emerging trends and early-stage developments
   - Experimental tools, prototypes, and proof-of-concepts
   - Cross-disciplinary applications and novel approaches
6. OBSCURE queries (3 queries) — find what no one else finds:
   - Niche forums, mailing lists, and community discussions
   - International sources and non-English publications
   - Academic and institutional research

Rules:
- Each query must be meaningfully different from the others
- Use quotation marks for exact phrases where helpful
- Use -"buy now" -"sign up" -"subscribe" to filter marketing noise
- Include temporal signals like "{year}" or "this week" in relevant queries
- Tailor ALL queries specifically to the research topic — do not use \
generic filler queries
- Return ONLY valid JSON. No markdown. No explanation. No backticks.

JSON format:
{{"topic": "string", "queries": [
  {{"id": "q01",
    "category": "CORE|DEPTH|FORMAT|RESEARCHER|EMERGING|OBSCURE",
    "query": "the actual search query string",
    "rationale": "why this query finds unique content"}}
]}}"""

FALLBACK_QUERY_TEMPLATES = [
    ("q01", "CORE", "{topic} latest news {year}", "broad coverage"),
    ("q02", "CORE", "{topic} research developments {year}", "research angle"),
    ("q03", "DEPTH", "site:github.com {topic} {year}", "GitHub projects"),
    ("q04", "RESEARCHER", "{topic} expert blog writeup {year}", "expert blogs"),
    ("q05", "EMERGING", "{topic} new tools techniques {year}", "emerging work"),
]


def _build_fallback(topic: str) -> list[SearchQuery]:
    year = datetime.now(UTC).year
    return [
        SearchQuery(id=id_, category=cat,
                    query=q.format(topic=topic, year=year),
                    rationale=r)
        for id_, cat, q, r in FALLBACK_QUERY_TEMPLATES
    ]


def generate_queries(
    topic: str,
    about_me: str,
    client: anthropic.Anthropic,
    domain_context: str = "",
) -> QueryPlan:
    year = datetime.now(UTC).year
    prompt = QUERY_GEN_PROMPT.format(
        about_me=about_me or "Not provided",
        topic=topic,
        year=year,
    )
    if domain_context:
        prompt += (
            f"\n\nDomain-specific guidance:\n{domain_context}\n"
            "Incorporate these domain priorities into your queries."
        )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        parsed = json.loads(text)
        queries = [
            SearchQuery(
                id=q["id"],
                category=q["category"],
                query=q["query"],
                rationale=q["rationale"],
            )
            for q in parsed["queries"]
        ]

        if len(queries) < 5:
            logger.warning(
                "Query generation returned only %d queries, using fallback",
                len(queries),
            )
            fallback = _build_fallback(topic)
            return QueryPlan(
                topic=topic, queries=fallback, generated_at=datetime.now(UTC),
            )

        logger.info(
            "Generated %d queries across %d categories",
            len(queries),
            len({q.category for q in queries}),
        )
        return QueryPlan(topic=topic, queries=queries, generated_at=datetime.now(UTC))

    except Exception:
        logger.warning("Query generation failed, using fallback", exc_info=True)
        fallback = _build_fallback(topic)
        return QueryPlan(
            topic=topic, queries=fallback, generated_at=datetime.now(UTC),
        )
