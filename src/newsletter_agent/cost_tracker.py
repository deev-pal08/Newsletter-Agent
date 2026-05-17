"""Lightweight per-run cost tracker."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class CostBreakdown:
    """Accumulates estimated costs for each pipeline stage."""

    discovery_tavily_credits: int = 0
    extraction_firecrawl: float = 0.0
    dedup_openai: float = 0.0
    filtering_deepseek: float = 0.0
    ranking_claude: float = 0.0
    _details: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return (
            self.extraction_firecrawl
            + self.dedup_openai
            + self.filtering_deepseek
            + self.ranking_claude
        )

    def add_tavily(self, searches: int, depth: str = "advanced") -> None:
        credits_per = 4 if depth == "advanced" else 1
        self.discovery_tavily_credits += searches * credits_per
        self._details["discovery"] = f"{searches} queries x {credits_per} credits"

    def add_filter(self, articles: int) -> None:
        self.filtering_deepseek += 0.025
        self._details["filter"] = f"{articles} articles"

    def add_dedup(self, titles_embedded: int) -> None:
        # text-embedding-3-small: $0.02/1M tokens, ~10 tokens per title
        self.dedup_openai += titles_embedded * 10 * 0.00000002
        self._details["dedup"] = f"{titles_embedded} titles embedded"

    def add_ranking(self, articles: int, model: str, batch: bool = False) -> None:
        base = articles * 0.0013 if "sonnet" in model else articles * 0.00045
        if batch:
            base *= 0.5
        self.ranking_claude += base
        mode = "Batch" if batch else "Sync"
        self._details["ranking"] = f"{articles} articles, {model} ({mode})"

    def format(self) -> str:
        lines = ["\n\U0001f4ca Run cost estimate:"]
        d = self._details
        if self.discovery_tavily_credits > 0:
            lines.append(f"  Discovery (Tavily):       {self.discovery_tavily_credits} credits"
                         f"   ({d.get('discovery', '')})")
        if self.extraction_firecrawl > 0:
            lines.append(f"  Extraction (Firecrawl):   ${self.extraction_firecrawl:.3f}")
        if self.dedup_openai > 0:
            lines.append(f"  Dedup (OpenAI):           ${self.dedup_openai:.4f}"
                         f"   ({d.get('dedup', '')})")
        if self.filtering_deepseek > 0:
            lines.append(f"  Filtering (DeepSeek):     ${self.filtering_deepseek:.3f}"
                         f"   ({d.get('filter', '')})")
        if self.ranking_claude > 0:
            lines.append(f"  Ranking (Claude):         ${self.ranking_claude:.3f}"
                         f"   ({d.get('ranking', '')})")
        lines.append("  " + "─" * 35)
        lines.append(f"  Total (API):              ${self.total:.3f}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, float | int]:
        return {
            "discovery_tavily_credits": self.discovery_tavily_credits,
            "extraction_firecrawl": round(self.extraction_firecrawl, 4),
            "dedup_openai": round(self.dedup_openai, 6),
            "filtering_deepseek": round(self.filtering_deepseek, 4),
            "ranking_claude": round(self.ranking_claude, 4),
            "total_api_cost": round(self.total, 4),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
