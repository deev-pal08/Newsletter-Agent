"""CLI interface for Newsletter Agent."""

from __future__ import annotations

import logging
import sys

import click

from newsletter_agent.config import load_config


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Config file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, config: str, verbose: bool) -> None:
    """Newsletter Agent — Security & AI Research Intelligence Digest"""
    ctx.ensure_object(dict)
    _setup_logging(verbose)
    ctx.obj["config"] = load_config(config)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.pass_context
def fetch(ctx: click.Context) -> None:
    """Fetch new articles from all enabled sources."""
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config)
    articles = pipeline.run_fetch()

    click.echo(f"\nFetched {len(articles)} new articles:")
    for a in articles[:20]:
        click.echo(f"  [{a.source_name}] {a.title}")
    if len(articles) > 20:
        click.echo(f"  ... and {len(articles) - 20} more")


@cli.command()
@click.option("--model", "-m", help="Override LLM model for this run")
@click.pass_context
def digest(ctx: click.Context, model: str | None) -> None:
    """Fetch, rank, and print digest (no email)."""
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    d = pipeline.run_digest()

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  DIGEST — {d.date.strftime('%B %d, %Y')}")
    n = len(d.articles)
    click.echo(f"  {d.total_fetched} scanned | {d.total_after_dedup} new | {n} ranked")
    click.echo(f"  Generated in {d.generation_time_seconds:.1f}s")
    click.echo(f"{'=' * 60}\n")

    _print_section("CRITICAL — ACT NOW", d.critical, "red")
    _print_section("IMPORTANT — READ THIS WEEK", d.important, "yellow")
    _print_section("INTERESTING — QUEUE FOR WEEKEND", d.interesting, "blue")
    _print_section("REFERENCE — SAVE FOR LATER", d.reference, "white")


@cli.command()
@click.option("--model", "-m", help="Override LLM model for this run")
@click.option("--dry-run", is_flag=True, help="Generate HTML but don't send email")
@click.pass_context
def send(ctx: click.Context, model: str | None, dry_run: bool) -> None:
    """Full pipeline: fetch, rank, format, and send digest email."""
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    d = pipeline.run_send(dry_run=dry_run)

    if dry_run:
        click.echo(f"Dry run complete. {len(d.articles)} articles ranked.")
        click.echo("HTML preview saved to data/")
    else:
        click.echo(f"Digest sent! {len(d.articles)} articles across {len(d.sources_used)} sources.")


@cli.command()
@click.pass_context
def sources(ctx: click.Context) -> None:
    """List all configured sources and their status."""
    from newsletter_agent.sources import SOURCE_REGISTRY
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    click.echo(f"\n{'Source':<20} {'Enabled':<10} {'Last Fetch':<22} {'Articles':<10} {'Errors'}")
    click.echo("-" * 75)

    source_configs = {
        "rss": config.sources.rss,
        "arxiv": config.sources.arxiv,
        "hackernews": config.sources.hackernews,
        "github_trending": config.sources.github_trending,
        "reddit": config.sources.reddit,
        "hackerone": config.sources.hackerone,
        "oss_security": config.sources.oss_security,
        "conferences": config.sources.conferences,
    }

    for source_id, _source_cls in SOURCE_REGISTRY.items():
        toggle = source_configs.get(source_id)
        enabled = toggle.enabled if toggle else False
        meta = state.get_source_meta(source_id)
        last_fetch = meta.get("last_fetch", "never")
        if last_fetch != "never":
            last_fetch = last_fetch[:19].replace("T", " ")
        total = meta.get("total_articles_fetched", 0)
        errors = meta.get("consecutive_errors", 0)

        enabled_str = click.style("yes", fg="green") if enabled else click.style("no", fg="red")
        click.echo(f"  {source_id:<18} {enabled_str:<19} {last_fetch:<22} {total:<10} {errors}")


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current state: last run, article counts, source health."""
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    click.echo("\nNewsletter Agent Status")
    click.echo("-" * 40)
    last = state.last_run
    click.echo(f"  Last run:       {last.strftime('%Y-%m-%d %H:%M:%S') if last else 'never'}")
    click.echo(f"  Seen articles:  {state.seen_count}")
    click.echo(f"  State dir:      {config.state_dir}")
    click.echo(f"  LLM model:      {config.llm.model}")
    click.echo(f"  Email enabled:  {config.email.enabled}")


@cli.command(name="test-source")
@click.argument("source_name")
@click.pass_context
def test_source(ctx: click.Context, source_name: str) -> None:
    """Test a single source by fetching and printing results."""
    import asyncio

    from newsletter_agent.sources import SOURCE_REGISTRY

    config = ctx.obj["config"]
    if source_name not in SOURCE_REGISTRY:
        click.echo(f"Unknown source: {source_name}")
        click.echo(f"Available: {', '.join(SOURCE_REGISTRY.keys())}")
        sys.exit(1)

    source_cls = SOURCE_REGISTRY[source_name]

    # Instantiate with config
    if source_name == "rss":
        source = source_cls(feeds=config.rss_feeds)
    elif source_name == "arxiv":
        source = source_cls(
            categories=config.sources.arxiv.categories,
            max_results=config.sources.arxiv.max_results,
        )
    elif source_name == "hackernews":
        source = source_cls(
            min_score=config.sources.hackernews.min_score,
            max_stories=config.sources.hackernews.max_stories,
        )
    elif source_name == "reddit":
        source = source_cls(subreddits=config.reddit_subreddits)
    else:
        source = source_cls()

    click.echo(f"Testing source: {source.name} ({source.source_id})")
    click.echo(f"Available: {source.is_available()}")
    click.echo("Fetching...\n")

    articles = asyncio.run(source.fetch())
    click.echo(f"Found {len(articles)} articles:\n")
    for i, a in enumerate(articles[:15], 1):
        click.echo(f"  {i}. {a.title}")
        click.echo(f"     {a.url}")
        if a.raw_summary:
            summary = a.raw_summary[:100] + "..." if len(a.raw_summary) > 100 else a.raw_summary
            click.echo(f"     {summary}")
        click.echo()
    if len(articles) > 15:
        click.echo(f"  ... and {len(articles) - 15} more")


def _print_section(title: str, articles: list, color: str) -> None:  # type: ignore[type-arg]
    if not articles:
        return
    click.echo(click.style(f"  [{title}] ({len(articles)})", fg=color, bold=True))
    click.echo()
    for a in articles:
        click.echo(f"    {a.title}")
        click.echo(click.style(f"    {a.source_name}", fg="cyan"), nl=False)
        if a.published_at:
            click.echo(f" · {a.published_at.strftime('%b %d')}", nl=False)
        if a.score:
            click.echo(f" · Score: {a.score}", nl=False)
        click.echo()
        if a.ai_summary:
            click.echo(click.style(f"    {a.ai_summary}", fg="white"))
        click.echo(click.style(f"    {a.url}", fg="bright_black"))
        click.echo()
