"""CLI interface for Newsletter Agent."""

from __future__ import annotations

import logging
import sys

import click
from dotenv import load_dotenv

from newsletter_agent.config import load_config

load_dotenv()


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
    """Newsletter Agent — Personalized Research Intelligence Digest"""
    ctx.ensure_object(dict)
    _setup_logging(verbose)
    ctx.obj["config"] = load_config(config)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose


@cli.command()
@click.option("--model", "-m", help="Override LLM model for this run")
@click.option("--dry-run", is_flag=True, help="Generate HTML but don't send email")
@click.pass_context
def send(ctx: click.Context, model: str | None, dry_run: bool) -> None:
    """Full pipeline: fetch, web search, rank, format, and send digest email."""
    from newsletter_agent.pipeline import Pipeline

    config = ctx.obj["config"]
    pipeline = Pipeline(config, model_override=model)
    d = pipeline.run_send(dry_run=dry_run)

    if dry_run:
        click.echo(f"Dry run complete. {len(d.articles)} articles ranked.")
        click.echo("HTML preview saved to data/")
    else:
        n_sources = len(d.sources_used)
        click.echo(f"Digest sent! {len(d.articles)} articles across {n_sources} sources.")

    click.echo(pipeline.cost.format())
    click.echo(pipeline.report.format())


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

        extra = ""
        if source_id == "rss":
            feed_count = len(state.get_rss_feeds())
            extra = f" ({feed_count} feeds)"
        elif source_id == "reddit":
            sub_count = len(state.get_subreddits())
            extra = f" ({sub_count} subs)"
        elif source_id == "web":
            page_count = len(state.get_web_pages())
            extra = f" ({page_count} pages)"

        click.echo(
            f"  {source_id:<18} {enabled_str:<19} {last_fetch:<22} "
            f"{total:<10} {error_str}{extra}"
        )


@cli.command()
@click.pass_context
def resources(ctx: click.Context) -> None:
    """List all resources in the database."""
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)
    all_res = state.get_all_resources()

    if not all_res:
        click.echo("\nNo resources in the database.")
        return

    click.echo(f"\n  {len(all_res)} resources:\n")

    current_source_type = None
    for r in all_res:
        st = r["source_type"] or "reference"
        if st != current_source_type:
            current_source_type = st
            if st == "rss":
                label = "RSS Feeds (auto-fetched daily)"
            elif st == "reddit":
                label = "Subreddits (auto-fetched daily)"
            elif st == "web":
                label = "Web Pages (auto-fetched daily, AI-assisted)"
            else:
                label = "Other Resources (reference)"
            click.echo(click.style(f"  {label}", bold=True))

        enabled = r["enabled"]
        status = click.style("on", fg="green") if enabled else click.style("off", fg="red")
        origin = click.style(f"[{r['discovered_by']}]", fg="bright_black")
        click.echo(f"    {r['id']:>3}. [{status}] {r['name']}  {origin}")
        click.echo(click.style(f"         {r['url']}", fg="bright_black"))
        if r.get("description"):
            click.echo(click.style(f"         {r['description']}", fg="cyan"))

    click.echo()
    click.echo("  Use `newsletter add-resource` / `newsletter remove-resource <ID>`.")


@cli.command(name="add-resource")
@click.option("--name", "-n", required=True, help="Resource name")
@click.option("--url", "-u", required=True, help="Resource URL")
@click.option("--feed-url", "-f", default=None, help="RSS/Atom feed URL (makes it auto-fetchable)")
@click.option("--type", "-t", "res_type", default="blog",
              help="Resource type (blog, subreddit, youtube, etc.)")
@click.pass_context
def add_resource(ctx: click.Context, name: str, url: str, feed_url: str | None,
                 res_type: str) -> None:
    """Add a resource to the database."""
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    source_type = None
    if feed_url:
        source_type = "rss"
    elif res_type == "subreddit":
        source_type = "reddit"
        if not name.startswith("r/"):
            name = f"r/{name}"
    elif res_type == "web":
        source_type = "web"

    result = state.add_resource(
        name=name, url=url, feed_url=feed_url,
        resource_type=res_type, source_type=source_type,
        discovered_by="user",
    )

    if result is not None:
        if source_type == "rss":
            dest = "rss_feeds"
        elif source_type == "reddit":
            dest = "subreddits"
        elif source_type == "web":
            dest = "web_pages"
        else:
            dest = "resources"
        click.echo(f"Added '{name}' → {dest} (ID: {result})")
    else:
        click.echo(f"Resource already exists: {url}")


@cli.command(name="remove-resource")
@click.argument("resource_id", type=int)
@click.pass_context
def remove_resource(ctx: click.Context, resource_id: int) -> None:
    """Remove a resource from the database by ID."""
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    state = StateStore(config.state_dir)

    if state.remove_resource(resource_id):
        click.echo(f"Removed resource #{resource_id}.")
    else:
        click.echo(f"Resource #{resource_id} not found.")


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
    click.echo(f"  Resources:      {state.resource_count()}")
    click.echo(f"  RSS feeds:      {len(state.get_rss_feeds())}")
    click.echo(f"  Subreddits:     {len(state.get_subreddits())}")
    click.echo(f"  Web pages:      {len(state.get_web_pages())}")
    click.echo(f"  State backend:  SQLite ({config.state_dir}/newsletter.db)")
    click.echo(f"  LLM model:      {config.llm.model}")
    click.echo(f"  Email enabled:  {config.email.enabled}")
    click.echo(f"  Auto-disable:   {config.health.auto_disable} "
               f"(after {config.health.max_consecutive_failures} failures)")


@cli.command(name="test-source")
@click.argument("source_name")
@click.pass_context
def test_source(ctx: click.Context, source_name: str) -> None:
    """Test a single source by fetching and printing results."""
    import asyncio

    from newsletter_agent.report import RunReport
    from newsletter_agent.sources import SOURCE_REGISTRY, instantiate_source
    from newsletter_agent.state.store import StateStore

    config = ctx.obj["config"]
    if source_name not in SOURCE_REGISTRY:
        click.echo(f"Unknown source: {source_name}")
        click.echo(f"Available: {', '.join(SOURCE_REGISTRY.keys())}")
        sys.exit(1)

    state = StateStore(config.state_dir)
    source = instantiate_source(source_name, config, state)
    report = RunReport()

    click.echo(f"Testing source: {source.name} ({source.source_id})")
    click.echo(f"Available: {source.is_available()}")
    click.echo("Fetching...\n")

    articles = asyncio.run(source.fetch(report=report))
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

    click.echo(report.format())


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
        cost_json = state.get_digest_cost(detail)
        if cost_json:
            import json as _json
            cost_data = _json.loads(cost_json)
            total = cost_data.get("total", 0)
            click.echo(f"  Cost: ${total:.3f}")
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
@click.option("--time", "-t", "time_str", default="08:00", help="Email delivery time (HH:MM)")
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
    result = install_schedule(
        time_str=time_str,
        config_path=config_path,
    )
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
