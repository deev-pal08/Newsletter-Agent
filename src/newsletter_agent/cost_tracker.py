"""Lightweight per-run cost tracker."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class CostBreakdown:
    """Accumulates estimated costs for each pipeline stage."""

    discovery_tavily: float = 0.0
    extraction_firecrawl: float = 0.0
    filtering_deepseek: float = 0.0
    ranking_claude: float = 0.0
    _details: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return (
            self.discovery_tavily
            + self.extraction_firecrawl
            + self.filtering_deepseek
            + self.ranking_claude
        )

    def add_tavily(self, searches: int, depth: str = "advanced") -> None:
        cost_per = 0.016 if depth == "advanced" else 0.008
        self.discovery_tavily += searches * cost_per
        self._details["discovery"] = f"{searches} searches x ${cost_per}"

    def add_filter(self, articles: int) -> None:
        self.filtering_deepseek += 0.025
        self._details["filter"] = f"{articles} articles"

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
        if self.discovery_tavily > 0:
            lines.append(f"  Discovery (Tavily):       ${self.discovery_tavily:.3f}"
                         f"   ({d.get('discovery', '')})")
        if self.extraction_firecrawl > 0:
            lines.append(f"  Extraction (Firecrawl):   ${self.extraction_firecrawl:.3f}")
        if self.filtering_deepseek > 0:
            lines.append(f"  Filtering (DeepSeek):     ${self.filtering_deepseek:.3f}"
                         f"   ({d.get('filter', '')})")
        if self.ranking_claude > 0:
            lines.append(f"  Ranking (Claude):         ${self.ranking_claude:.3f}"
                         f"   ({d.get('ranking', '')})")
        lines.append("  " + "─" * 35)
        lines.append(f"  Total:                    ${self.total:.3f}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, float]:
        return {
            "discovery_tavily": round(self.discovery_tavily, 4),
            "extraction_firecrawl": round(self.extraction_firecrawl, 4),
            "filtering_deepseek": round(self.filtering_deepseek, 4),
            "ranking_claude": round(self.ranking_claude, 4),
            "total": round(self.total, 4),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
