"""Run health report — accumulates issues throughout a pipeline run."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunReport:
    """Tracks health/status info across all pipeline stages."""

    # Source fetching
    sources_ok: list[tuple[str, int]] = field(default_factory=list)
    sources_failed: list[tuple[str, str]] = field(default_factory=list)
    sources_skipped: list[tuple[str, str]] = field(default_factory=list)

    # Per-feed/subreddit granularity
    feeds_ok: list[str] = field(default_factory=list)
    feeds_failed: list[tuple[str, str]] = field(default_factory=list)

    # Web extraction
    web_extractions: list[tuple[str, str]] = field(default_factory=list)
    web_failures: list[tuple[str, str]] = field(default_factory=list)

    # Tavily discovery (legacy, kept for backward compat)
    tavily_queries_ok: int = 0
    tavily_articles: int = 0
    tavily_queries_failed: list[tuple[str, str]] = field(default_factory=list)
    tavily_skipped: str | None = None

    # Deep search engine
    search_layers_ok: list[tuple[str, int, float]] = field(default_factory=list)
    search_layers_failed: list[tuple[str, str]] = field(default_factory=list)
    search_unique_urls: int = 0
    search_high_confidence: int = 0

    # DeepSeek filtering
    filter_kept: int = 0
    filter_removed: int = 0
    filter_fallbacks: list[str] = field(default_factory=list)
    filter_skipped: str | None = None

    # Ranking
    ranking_mode: str = ""
    ranking_ok: bool = True
    ranking_fallback: str | None = None

    # Dedup
    dedup_removed: int = 0
    dedup_semantic: bool = False
    dedup_fallback: bool = False
    dedup_fallback_reason: str | None = None
    dedup_skipped: str | None = None

    # Delivery
    delivery_ok: bool = False
    delivery_error: str | None = None
    delivery_skipped: str | None = None

    def add_source_ok(self, name: str, count: int) -> None:
        self.sources_ok.append((name, count))

    def add_source_failed(self, name: str, error: str) -> None:
        self.sources_failed.append((name, error))

    def add_source_skipped(self, name: str, reason: str) -> None:
        self.sources_skipped.append((name, reason))

    def add_feed_ok(self, name: str) -> None:
        self.feeds_ok.append(name)

    def add_feed_failed(self, name: str, error: str) -> None:
        self.feeds_failed.append((name, error))

    def add_web_ok(self, page: str, strategy: str) -> None:
        self.web_extractions.append((page, strategy))

    def add_web_failed(self, page: str, error: str) -> None:
        self.web_failures.append((page, error))

    def add_tavily_ok(self, articles: int = 0) -> None:
        self.tavily_queries_ok += 1
        self.tavily_articles += articles

    def add_tavily_failed(self, query: str, error: str) -> None:
        self.tavily_queries_failed.append((query, error))

    def add_search_layer_ok(self, name: str, count: int, duration: float) -> None:
        self.search_layers_ok.append((name, count, duration))

    def add_search_layer_failed(self, name: str, error: str) -> None:
        self.search_layers_failed.append((name, error))

    @property
    def has_issues(self) -> bool:
        return bool(
            self.sources_failed
            or self.sources_skipped
            or self.feeds_failed
            or self.web_failures
            or self.tavily_queries_failed
            or self.filter_fallbacks
            or self.filter_skipped
            or not self.ranking_ok
            or self.dedup_fallback
            or self.dedup_skipped
            or self.delivery_error
        )

    def format(self) -> str:
        lines = ["", "--- Run Health ---"]

        # Sources
        ok_count = len(self.sources_ok)
        fail_count = len(self.sources_failed)
        skip_count = len(self.sources_skipped)
        if ok_count and not fail_count and not skip_count:
            parts = ", ".join(f"{n}: {c}" for n, c in self.sources_ok)
            lines.append(f"  Sources:   {ok_count} OK ({parts})")
        else:
            status_parts: list[str] = []
            if ok_count:
                status_parts.append(f"{ok_count} OK")
            if fail_count:
                status_parts.append(f"{fail_count} failed")
            if skip_count:
                status_parts.append(f"{skip_count} skipped")
            lines.append(f"  Sources:   {', '.join(status_parts)}")
            for name, count in self.sources_ok:
                lines.append(f"    [OK]   {name}: {count} articles")
            for name, error in self.sources_failed:
                lines.append(f"    [FAIL] {name}: {error}")
            for name, reason in self.sources_skipped:
                lines.append(f"    [SKIP] {name}: {reason}")

        # Warnings (feed/web failures)
        warnings = []
        for name, error in self.feeds_failed:
            warnings.append(f'Feed "{name}": {error}')
        for page, error in self.web_failures:
            warnings.append(f'Web "{page}": {error}')
        if warnings:
            lines.append("  Warnings:")
            for w in warnings:
                lines.append(f"    - {w}")

        # Tavily (legacy, only shown if old scanner was used)
        total_queries = self.tavily_queries_ok + len(self.tavily_queries_failed)
        if self.tavily_skipped:
            lines.append(f"  Discovery: skipped ({self.tavily_skipped})")
        elif total_queries:
            if not self.tavily_queries_failed:
                lines.append(
                    f"  Discovery: {self.tavily_queries_ok}/{total_queries} "
                    f"Tavily queries OK, {self.tavily_articles} articles"
                )
            else:
                lines.append(
                    f"  Discovery: {self.tavily_queries_ok}/{total_queries} "
                    f"Tavily queries OK"
                )
                for query, error in self.tavily_queries_failed:
                    short = query[:60] + "..." if len(query) > 60 else query
                    lines.append(f'    - "{short}": {error}')

        # Deep search engine
        if self.search_layers_ok or self.search_layers_failed:
            ok_count = len(self.search_layers_ok)
            fail_count = len(self.search_layers_failed)
            total_results = sum(c for _, c, _ in self.search_layers_ok)
            lines.append(
                f"  Search:    {ok_count} layers OK, {total_results} raw -> "
                f"{self.search_unique_urls} unique URLs"
            )
            for name, count, dur in self.search_layers_ok:
                lines.append(f"    [OK]   {name}: {count} results in {dur:.1f}s")
            for name, error in self.search_layers_failed:
                lines.append(f"    [FAIL] {name}: {error}")
            if self.search_high_confidence:
                lines.append(
                    f"    High confidence (3+ layers): {self.search_high_confidence} URLs"
                )

        # Filter
        if self.filter_skipped:
            lines.append(f"  Filter:    skipped ({self.filter_skipped})")
        elif self.filter_kept or self.filter_removed:
            line = f"  Filter:    {self.filter_kept} kept, {self.filter_removed} removed"
            if self.filter_fallbacks:
                line += f" ({len(self.filter_fallbacks)} batch failures, fail-open)"
            lines.append(line)

        # Ranking
        if self.ranking_mode:
            if self.ranking_ok:
                lines.append(f"  Ranking:   OK ({self.ranking_mode})")
            else:
                lines.append(f"  Ranking:   degraded ({self.ranking_fallback})")

        # Dedup
        if self.dedup_skipped:
            lines.append(f"  Dedup:     {self.dedup_skipped}")
        elif self.dedup_fallback:
            reason = ""
            if self.dedup_fallback_reason:
                reason = f" ({self.dedup_fallback_reason})"
            lines.append(
                f"  Dedup:     fell back to title similarity{reason}, "
                f"removed {self.dedup_removed}"
            )
        elif self.dedup_semantic:
            lines.append(
                f"  Dedup:     semantic, removed {self.dedup_removed}"
            )

        # Delivery
        if self.delivery_ok:
            lines.append("  Delivery:  sent")
        elif self.delivery_error:
            lines.append(f"  Delivery:  failed ({self.delivery_error})")
        elif self.delivery_skipped:
            lines.append(f"  Delivery:  {self.delivery_skipped}")

        lines.append("")
        return "\n".join(lines)
