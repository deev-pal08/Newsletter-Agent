# Newsletter Agent

## Project Overview
Automated intelligence-gathering system for personalized research.
Monitors curated sources, discovers new ones via web search,
uses Claude API for ranking/categorization based on user profile,
delivers prioritized daily digest via Resend email.

## Tech Stack
- Python 3.12, managed with uv
- Claude API (anthropic SDK) for article ranking and source discovery
- Resend API for email delivery
- Click for CLI
- Pydantic for config validation and data models
- httpx for async HTTP, feedparser for RSS, BeautifulSoup for scraping
- SQLite for state persistence AND resource management (v2)

## Project Structure
- `src/newsletter_agent/` — main package (src layout)
- `src/newsletter_agent/sources/` — one module per data source, all extend BaseSource
- `src/newsletter_agent/ranking/` — Claude API integration for prioritization
- `src/newsletter_agent/delivery/` — Resend email + HTML templates
- `src/newsletter_agent/state/` — SQLite state persistence + resource DB
- `src/newsletter_agent/scanner.py` — web-based source discovery (Claude + web search)
- `src/newsletter_agent/utils.py` — URL normalization, title similarity
- `src/newsletter_agent/scheduling.py` — LaunchAgent/crontab/Task Scheduler scheduling
- `AboutMe.md` — user profile (skills, interests, learning goals)
- `tests/` — mirrors src structure
- `config.yaml` — operational config only (no URLs — those live in the DB)

## Key Commands
```bash
uv run newsletter send                  # full pipeline: fetch, rank, email
uv run newsletter send --dry-run        # preview without sending
uv run newsletter send --batch          # use Batch API (50% cheaper)
uv run newsletter send -m claude-sonnet-4-6  # use Sonnet for ranking
uv run newsletter fetch                 # fetch only, no ranking
uv run newsletter digest                # fetch + rank, print to terminal
uv run newsletter digest --batch        # digest via Batch API
uv run newsletter scan                  # discover new resources via web search
uv run newsletter scan --dry-run        # preview discoveries without adding
uv run newsletter scan --auto           # auto-add all discovered resources
uv run newsletter resources             # list all resources in DB
uv run newsletter add-resource          # manually add a resource
uv run newsletter remove-resource <ID>  # remove a resource by DB ID
uv run newsletter test-source <id>      # debug one source
uv run newsletter sources               # list source status + health
uv run newsletter status                # show state (SQLite backend)
uv run newsletter history               # browse past digests
uv run newsletter history --detail <ID> # view full past digest
uv run newsletter batch-submit          # submit for async batch ranking
uv run newsletter batch-collect         # collect batch results
uv run newsletter batch-collect --send-email  # collect + send email
uv run newsletter install-schedule      # install daily schedule
uv run newsletter install-schedule --batch    # async batch schedule (50% cheaper)
uv run newsletter install-schedule --uninstall  # remove schedule
uv run newsletter re-enable <source>    # reset error count for a source
uv run pytest                           # run tests
uv run ruff check src/ tests/           # lint
uv run mypy src/                        # type check
```

## Architecture Rules
- Every source implements BaseSource (sources/base.py)
- Pipeline flow: fetch → deduplicate → rank → format → deliver
- No source-specific logic in pipeline.py
- All HTTP requests use httpx (async)
- State AND resources are SQLite in data/newsletter.db (gitignored)
- No hardcoded URLs in config — all resources (RSS feeds, subreddits, etc.) live in the DB
- Config.yaml is operational settings only (toggles, thresholds, API key env vars)
- Config is validated by Pydantic at load time
- API keys come from environment variables, never config files
- Sources use `instantiate_source()` in sources/__init__.py for construction
- `RSSSource` and `RedditSource` read their URLs/subreddits from the resources table
- User profile (AboutMe.md) is injected into ranking prompts for personalization

## Resource Management
- All resources (RSS feeds, subreddits, YouTube channels, etc.) are stored in the `resources` table in SQLite
- The database starts empty — users populate it via `scan` or `add-resource`
- Resources with `source_type='rss'` are auto-fetched daily by the RSS source
- Resources with `source_type='reddit'` are auto-fetched daily by the Reddit source
- Resources with `source_type=NULL` are reference-only (bookmarks)
- `discovered_by` tracks origin: 'user' or 'scan'
- Manage via CLI: `newsletter resources`, `newsletter add-resource`, `newsletter remove-resource`

## Source Discovery (scan command)
- Uses Claude Sonnet + web search to find ANY resource type: blogs, YouTube channels, podcasts, newsletters, forums, courses, tools, communities, etc.
- Completely driven by the user's AboutMe.md profile and interests — works for any domain
- All discoveries are written directly to the SQLite database
- Resources with RSS feeds get `source_type='rss'` (auto-fetched daily)
- Subreddits get `source_type='reddit'` (auto-fetched daily)
- Everything else is stored as reference resources
- Compares against all existing DB entries to avoid duplicates
- Interactive: user selects which discoveries to add
- Not part of the daily pipeline — run manually when you want new resources

## Adding a New Source
1. Create `src/newsletter_agent/sources/my_source.py`
2. Implement BaseSource (name, source_id, fetch method)
3. Register in `sources/__init__.py` SOURCE_REGISTRY
4. Add toggle in config.py SourcesConfig
5. Wire up instantiation in `sources/__init__.py` instantiate_source()
6. Add tests in `tests/sources/test_my_source.py`

## Source IDs
rss, arxiv, hackernews, github_trending, reddit, hackerone, oss_security, conferences

## Environment Variables
- `ANTHROPIC_API_KEY` — required for ranking and scanning
- `RESEND_API_KEY` — required for email delivery

## Priority Taxonomy
- `CRITICAL - ACT NOW` — urgent, time-sensitive, directly impacts user's work
- `IMPORTANT - READ THIS WEEK` — relevant paper/tool/update, not urgent
- `INTERESTING - QUEUE FOR WEEKEND` — worth reading, not time-sensitive
- `REFERENCE - SAVE FOR LATER` — archive for future use

## v2 Features
- **SQLite state**: Replaced JSON with SQLite (WAL mode), auto-migrates from state.json
- **Fuzzy dedup**: URL normalization (strip tracking params), title fingerprinting, cross-source similarity matching (difflib, 85% threshold)
- **Source health**: Auto-disables sources after 3 consecutive failures, 24h retry cooldown, `re-enable` command to reset
- **Digest history**: Browse past digests with search, date filters, and detail view
- **Batch API**: 50% cheaper ranking via Claude Batch API — inline (`--batch`) and async (`batch-submit`/`batch-collect`) modes
- **Cross-platform scheduling**: Daily jobs on macOS (launchd), Linux (cron), Windows (Task Scheduler) — sync and async batch modes
- **User profile**: AboutMe.md drives personalized ranking and source discovery
- **Source scanner**: `scan` command uses Claude + web search to discover new sources
