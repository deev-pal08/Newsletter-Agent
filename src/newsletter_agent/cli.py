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
    ctx.obj["config_path"] = config
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
@click.option("--batch", is_flag=True, help="Use Batch API (50% cheaper, slower)")
@click.pass_context
def digest(ctx: click.Context, model: str | None, batch: bool) -> None:
    """Fetch, rank, and print digest (no email)."""
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    d = pipeline.run_digest(use_batch=batch)

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  DIGEST — {d.date.strftime('%B %d, %Y')}")
    n = len(d.articles)
    click.echo(f"  {d.total_fetched} scanned | {d.total_after_dedup} new | {n} ranked")
    click.echo(f"  Generated in {d.generation_time_seconds:.1f}s")
    if batch:
        click.echo("  Mode: Batch API (50% cheaper)")
    click.echo(f"{'=' * 60}\n")

    _print_section("CRITICAL — ACT NOW", d.critical, "red")
    _print_section("IMPORTANT — READ THIS WEEK", d.important, "yellow")
    _print_section("INTERESTING — QUEUE FOR WEEKEND", d.interesting, "blue")
    _print_section("REFERENCE — SAVE FOR LATER", d.reference, "white")


@cli.command()
@click.option("--model", "-m", help="Override LLM model for this run")
@click.option("--dry-run", is_flag=True, help="Generate HTML but don't send email")
@click.option("--batch", is_flag=True, help="Use Batch API (50% cheaper, slower)")
@click.pass_context
def send(ctx: click.Context, model: str | None, dry_run: bool, batch: bool) -> None:
    """Full pipeline: fetch, rank, format, and send digest email."""
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    d = pipeline.run_send(dry_run=dry_run, use_batch=batch)

    if dry_run:
        click.echo(f"Dry run complete. {len(d.articles)} articles ranked.")
        if batch:
            click.echo("Mode: Batch API (50% cheaper)")
        click.echo("HTML preview saved to data/")
    else:
        n_sources = len(d.sources_used)
        click.echo(f"Digest sent! {len(d.articles)} articles across {n_sources} sources.")


@cli.command()
@click.pass_context
def sources(ctx: click.Context) -> None:
    """List all configured sources and their status."""
    from newsletter_agent.sources import SOURCE_REGISTRY, is_source_enabled
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    header = f"{'Source':<20} {'Enabled':<10} {'Last Fetch':<22} {'Articles':<10} {'Errors'}"
    click.echo(f"\n{header}")
    click.echo("-" * 75)

    for source_id in SOURCE_REGISTRY:
        enabled = is_source_enabled(source_id, config)
        meta = state.get_source_meta(source_id)
        last_fetch = meta.get("last_fetch", "never") or "never"
        if last_fetch != "never":
            last_fetch = str(last_fetch)[:19].replace("T", " ")
        total = meta.get("total_articles_fetched", 0)
        errors = meta.get("consecutive_errors", 0)

        enabled_str = click.style("yes", fg="green") if enabled else click.style("no", fg="red")
        error_str = click.style(str(errors), fg="red") if errors > 0 else str(errors)
        click.echo(f"  {source_id:<18} {enabled_str:<19} {last_fetch:<22} {total:<10} {error_str}")


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current state: last run, article counts, source health."""
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    click.echo("\nNewsletter Agent Status (v2)")
    click.echo("-" * 40)
    last = state.last_run
    click.echo(f"  Last run:       {last.strftime('%Y-%m-%d %H:%M:%S') if last else 'never'}")
    click.echo(f"  Seen articles:  {state.seen_count}")
    click.echo(f"  State backend:  SQLite ({config.state_dir}/newsletter.db)")
    click.echo(f"  LLM model:      {config.llm.model}")
    click.echo(f"  Email enabled:  {config.email.enabled}")
    click.echo(f"  Fuzzy dedup:    {config.dedup.fuzzy_url}")
    click.echo(f"  Auto-disable:   {config.health.auto_disable} "
               f"(after {config.health.max_consecutive_failures} failures)")


@cli.command(name="test-source")
@click.argument("source_name")
@click.pass_context
def test_source(ctx: click.Context, source_name: str) -> None:
    """Test a single source by fetching and printing results."""
    import asyncio

    from newsletter_agent.sources import SOURCE_REGISTRY, instantiate_source

    config = ctx.obj["config"]
    if source_name not in SOURCE_REGISTRY:
        click.echo(f"Unknown source: {source_name}")
        click.echo(f"Available: {', '.join(SOURCE_REGISTRY.keys())}")
        sys.exit(1)

    source = instantiate_source(source_name, config)

    click.echo(f"Testing source: {source.name} ({source.source_id})")
    click.echo(f"Available: {source.is_available()}")
    click.echo("Fetching...\n")

    articles = asyncio.run(source.fetch())
    click.echo(f"Found {len(articles)} articles:\n")
    for i, a in enumerate(articles[:15], 1):
        click.echo(f"  {i}. {a.title}")
        click.echo(f"     {a.url}")
        if a.raw_summary:
            s = a.raw_summary[:100] + "..." if len(a.raw_summary) > 100 else a.raw_summary
            click.echo(f"     {s}")
        click.echo()
    if len(articles) > 15:
        click.echo(f"  ... and {len(articles) - 15} more")


@cli.command()
@click.option("--limit", "-n", default=10, help="Number of digests to show")
@click.option("--since", type=str, default=None, help="Show digests from this date (YYYY-MM-DD)")
@click.option("--until", type=str, default=None, help="Show digests until this date (YYYY-MM-DD)")
@click.option("--search", "-s", type=str, default=None, help="Search in article titles")
@click.option("--detail", "-d", type=int, default=None, help="Show full digest by ID")
@click.pass_context
def history(ctx: click.Context, limit: int, since: str | None, until: str | None,
            search: str | None, detail: int | None) -> None:
    """Browse past digest history."""
    from datetime import datetime

    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    if detail is not None:
        d = state.get_digest_by_id(detail)
        if d is None:
            click.echo(f"Digest #{detail} not found.")
            return
        click.echo(f"\n{'=' * 60}")
        click.echo(f"  DIGEST #{d.digest_id} — {d.date.strftime('%B %d, %Y %H:%M')}")
        n = len(d.articles)
        click.echo(f"  {d.total_fetched} scanned | {d.total_after_dedup} new | {n} ranked")
        email = "Yes" if d.email_sent else "No"
        click.echo(f"  Email sent: {email}")
        click.echo(f"{'=' * 60}\n")
        _print_section("CRITICAL — ACT NOW", d.critical, "red")
        _print_section("IMPORTANT — READ THIS WEEK", d.important, "yellow")
        _print_section("INTERESTING — QUEUE FOR WEEKEND", d.interesting, "blue")
        _print_section("REFERENCE — SAVE FOR LATER", d.reference, "white")
        return

    date_from = datetime.fromisoformat(since) if since else None
    date_to = datetime.fromisoformat(until) if until else None
    digests = state.get_digest_history(
        limit=limit, date_from=date_from, date_to=date_to, search=search,
    )

    if not digests:
        click.echo("\nNo digests found.")
        return

    click.echo(f"\n{'ID':<6} {'Date':<22} {'Articles':<10} {'Critical':<10} {'Email'}")
    click.echo("-" * 60)
    for d in digests:
        date_str = str(d["date"])[:19].replace("T", " ")
        email = click.style("sent", fg="green") if d["email_sent"] else "no"
        crit = d["critical_count"]
        crit_str = click.style(str(crit), fg="red") if crit > 0 else str(crit)
        click.echo(f"  {d['id']:<4} {date_str:<22} {d['article_count']:<10} {crit_str:<18} {email}")

    click.echo("\nUse `newsletter history --detail <ID>` to view a specific digest.")


@cli.command(name="install-schedule")
@click.option("--time", "-t", "time_str", default="08:00", help="Daily run time (HH:MM)")
@click.option("--uninstall", is_flag=True, help="Remove the installed schedule")
@click.pass_context
def install_schedule_cmd(ctx: click.Context, time_str: str, uninstall: bool) -> None:
    """Install or remove a daily schedule (launchd/cron)."""
    from newsletter_agent.scheduling import install_schedule, uninstall_schedule

    if uninstall:
        removed = uninstall_schedule()
        if removed:
            click.echo("Schedule removed.")
        else:
            click.echo("No schedule found to remove.")
        return

    config_path = ctx.obj["config_path"]
    result = install_schedule(time_str=time_str, config_path=config_path)
    click.echo(f"Schedule installed: daily at {time_str}")
    click.echo(f"  {result}")
    click.echo("  Logs: data/logs/newsletter-*.log")


@cli.command(name="re-enable")
@click.argument("source_name")
@click.pass_context
def re_enable(ctx: click.Context, source_name: str) -> None:
    """Reset error count for a disabled source."""
    from newsletter_agent.sources import SOURCE_REGISTRY
    from newsletter_agent.state.store import StateStore

    if source_name not in SOURCE_REGISTRY:
        click.echo(f"Unknown source: {source_name}")
        click.echo(f"Available: {', '.join(SOURCE_REGISTRY.keys())}")
        sys.exit(1)

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)
    if state.reset_source_errors(source_name):
        click.echo(f"Source '{source_name}' re-enabled. Error count reset to 0.")
    else:
        click.echo(f"Source '{source_name}' has no error history.")


@cli.command(name="batch-submit")
@click.option("--model", "-m", help="Override LLM model for this run")
@click.pass_context
def batch_submit(ctx: click.Context, model: str | None) -> None:
    """Submit articles for async batch ranking (50% cheaper).

    Fetches and deduplicates articles, then submits them to the
    Claude Batch API. Results are collected later with batch-collect.
    """
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    batch_id = pipeline.run_batch_submit()

    if batch_id:
        click.echo(f"Batch submitted: {batch_id}")
        click.echo("Run `newsletter batch-collect` to check results.")
    else:
        click.echo("No new articles to rank.")


@cli.command(name="batch-collect")
@click.option("--batch-id", "-b", default=None, help="Specific batch ID to collect")
@click.option("--send-email", is_flag=True, help="Send digest email if results are ready")
@click.option("--model", "-m", help="Override LLM model for this run")
@click.pass_context
def batch_collect(ctx: click.Context, batch_id: str | None, send_email: bool,
                  model: str | None) -> None:
    """Collect results from a pending batch job.

    If the batch is still processing, shows the current status.
    If complete, builds the digest and optionally sends the email.
    """
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    digest = pipeline.run_batch_collect(batch_id=batch_id)

    if digest is None:
        pending = pipeline.state.get_pending_batch()
        if pending:
            click.echo(f"Batch {pending['batch_id']} is still processing.")
            click.echo("Run this command again later.")
        else:
            click.echo("No pending batch jobs.")
        return

    n = len(digest.articles)
    click.echo(f"\nBatch complete! {n} articles ranked.")
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  DIGEST — {digest.date.strftime('%B %d, %Y')}")
    click.echo(f"{'=' * 60}\n")

    _print_section("CRITICAL — ACT NOW", digest.critical, "red")
    _print_section("IMPORTANT — READ THIS WEEK", digest.important, "yellow")
    _print_section("INTERESTING — QUEUE FOR WEEKEND", digest.interesting, "blue")
    _print_section("REFERENCE — SAVE FOR LATER", digest.reference, "white")

    if send_email and pipeline.delivery:
        email_id = pipeline.delivery.send_digest(digest)
        if digest.digest_id:
            pipeline.state.update_digest_email(digest.digest_id, email_id)
        click.echo(f"Digest email sent! (email_id={email_id})")


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
