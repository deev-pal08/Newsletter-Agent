# Newsletter Agent

Automated intelligence-gathering system for security and AI research. Monitors curated sources, uses Claude to filter signal from noise, and delivers a prioritized daily digest via email.

## What It Does

1. **Fetches** from 8 source types: security blogs (RSS), arXiv papers, Hacker News, GitHub Trending, Reddit, HackerOne disclosures, oss-security mailing list, and conference proceedings
2. **Deduplicates** against previously seen articles
3. **Ranks** using Claude AI into four priority levels: Critical, Important, Interesting, Reference
4. **Delivers** a formatted HTML email via Resend

## Quick Start

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and set up
git clone <your-repo-url>
cd newsletter-agent
cp config.example.yaml config.yaml
cp .env.example .env

# Edit .env with your API keys
# Edit config.yaml with your interests and email

# Install dependencies
uv sync

# Test a source
uv run newsletter test-source hackernews

# Preview a full digest
uv run newsletter send --dry-run

# Send for real
uv run newsletter send
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

- **interests**: Your research focus areas (used by Claude for ranking)
- **rss_feeds**: RSS/Atom feed URLs to monitor
- **reddit_subreddits**: Subreddits to follow
- **sources**: Toggle individual sources on/off
- **llm.model**: `claude-haiku-4-5` (cheap) or `claude-sonnet-4-6` (better)
- **email**: Resend delivery settings

## Commands

| Command | Description |
|---------|-------------|
| `newsletter send` | Full pipeline: fetch, rank, email |
| `newsletter send --dry-run` | Generate HTML without sending |
| `newsletter digest` | Fetch + rank, print to terminal |
| `newsletter fetch` | Fetch only, print summary |
| `newsletter test-source <id>` | Debug a single source |
| `newsletter sources` | Show source status table |
| `newsletter status` | Show system state |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for ranking |
| `RESEND_API_KEY` | Yes (for email) | Resend API key for delivery |

## Cost

Using Claude Haiku (default): ~$0.045 per run, ~$1.35/month for daily use.
Using Claude Sonnet: ~$0.135 per run, ~$4.05/month.

## Sources

| Source | Method | API Key Required |
|--------|--------|-----------------|
| Security blogs (9) | RSS feeds | No |
| arXiv (cs.CR, cs.AI, cs.LG) | Public API | No |
| Hacker News | Firebase API | No |
| GitHub Trending | HTML scraping | No |
| Reddit (4 subs) | Public RSS | No |
| oss-security | Web scraping | No |
| HackerOne | GraphQL (experimental) | No |
| Conferences | Web scraping | No |

## Project Structure

```
src/newsletter_agent/
├── cli.py              # Click CLI
├── config.py           # Pydantic config
├── models.py           # Article, Priority, Digest
├── pipeline.py         # Orchestrator
├── sources/            # Source plugins (one per file)
├── ranking/            # Claude API ranking
├── delivery/           # Resend email + templates
└── state/              # JSON persistence
```

## Adding a New Source

1. Create `src/newsletter_agent/sources/my_source.py` implementing `BaseSource`
2. Register in `sources/__init__.py`
3. Add config toggle in `config.py`
4. Wire up in `get_enabled_sources()`

## License

MIT
