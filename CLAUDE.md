# Newsletter Agent

## Project Overview
Automated intelligence-gathering system for security and AI research.
Monitors curated sources, uses Claude API for ranking/categorization,
delivers prioritized daily digest via Resend email.

## Tech Stack
- Python 3.12, managed with uv
- Claude API (anthropic SDK) for article ranking
- Resend API for email delivery
- Click for CLI
- Pydantic for config validation and data models
- httpx for async HTTP, feedparser for RSS, BeautifulSoup for scraping

## Project Structure
- `src/newsletter_agent/` — main package (src layout)
- `src/newsletter_agent/sources/` — one module per data source, all extend BaseSource
- `src/newsletter_agent/ranking/` — Claude API integration for prioritization
- `src/newsletter_agent/delivery/` — Resend email + HTML templates
- `src/newsletter_agent/state/` — JSON file persistence
- `tests/` — mirrors src structure
- `config.yaml` — user configuration (copy from config.example.yaml)

## Key Commands
```bash
uv run newsletter send              # full pipeline: fetch, rank, email
uv run newsletter send --dry-run    # preview without sending
uv run newsletter send -m claude-sonnet-4-6  # use Sonnet for ranking
uv run newsletter fetch             # fetch only, no ranking
uv run newsletter digest            # fetch + rank, print to terminal
uv run newsletter test-source <id>  # debug one source
uv run newsletter sources           # list source status
uv run newsletter status            # show state
uv run pytest                       # run tests
uv run ruff check src/ tests/       # lint
uv run mypy src/                    # type check
```

## Architecture Rules
- Every source implements BaseSource (sources/base.py)
- Pipeline flow: fetch → deduplicate → rank → format → deliver
- No source-specific logic in pipeline.py
- All HTTP requests use httpx (async)
- State is JSON files in data/ (gitignored)
- Config is validated by Pydantic at load time
- API keys come from environment variables, never config files

## Adding a New Source
1. Create `src/newsletter_agent/sources/my_source.py`
2. Implement BaseSource (name, source_id, fetch method)
3. Register in `sources/__init__.py` SOURCE_REGISTRY
4. Add toggle in config.py SourcesConfig
5. Wire up instantiation in `sources/__init__.py` get_enabled_sources()
6. Add tests in `tests/sources/test_my_source.py`

## Source IDs
rss, arxiv, hackernews, github_trending, reddit, hackerone, oss_security, conferences

## Environment Variables
- `ANTHROPIC_API_KEY` — required for ranking
- `RESEND_API_KEY` — required for email delivery

## Priority Taxonomy
- `CRITICAL - ACT NOW` — active CVE/exploit in studied domains
- `IMPORTANT - READ THIS WEEK` — relevant paper/tool, not urgent
- `INTERESTING - QUEUE FOR WEEKEND` — worth reading, not time-sensitive
- `REFERENCE - SAVE FOR LATER` — archive for future use
