# Newsletter Agent

Automated intelligence-gathering system for security and AI research. Monitors curated sources, uses Claude to filter signal from noise, and delivers a prioritized daily digest via email.

## What It Does

1. **Fetches** from 8 source types: security blogs (RSS), arXiv papers, Hacker News, GitHub Trending, Reddit, HackerOne disclosures, oss-security mailing list, and conference proceedings
2. **Deduplicates** using URL normalization, title fingerprinting, and cross-source fuzzy matching
3. **Ranks** using Claude AI into four priority levels: Critical, Important, Interesting, Reference
4. **Delivers** a formatted HTML email via Resend
5. **Tracks** source health, digest history, and seen articles in SQLite

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- [Anthropic API key](https://console.anthropic.com/) for article ranking
- [Resend API key](https://resend.com/) for email delivery (free tier: 100 emails/day)

## Quick Start

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repo
git clone https://github.com/deev-pal08/Newsletter-Agent.git
cd Newsletter-Agent

# 3. Install dependencies
uv sync

# 4. Set up your config
cp config.example.yaml config.yaml
# Edit config.yaml — add your email under email.to_addresses,
# customize interests, toggle sources on/off

# 5. Set up API keys
cp .env.example .env
# Edit .env — paste your Anthropic and Resend API keys

# 6. Test a source
uv run newsletter test-source hackernews

# 7. Preview a full ranked digest (requires Anthropic key)
uv run newsletter send --dry-run

# 8. Send for real (requires both keys)
uv run newsletter send

# 9. (Optional) Install daily schedule
uv run newsletter install-schedule --time 08:00
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

- **interests**: Your research focus areas (used by Claude for ranking)
- **rss_feeds**: RSS/Atom feed URLs to monitor
- **reddit_subreddits**: Subreddits to follow
- **sources**: Toggle individual sources on/off
- **llm.model**: `claude-haiku-4-5` (cheap) or `claude-sonnet-4-6` (better)
- **email**: Resend delivery settings
- **dedup**: Fuzzy URL matching and title similarity threshold
- **health**: Auto-disable failing sources, retry cooldown
- **schedule**: Daily digest time and timezone

## Commands

| Command | Description |
|---------|-------------|
| `newsletter send` | Full pipeline: fetch, rank, email |
| `newsletter send --dry-run` | Generate HTML without sending |
| `newsletter digest` | Fetch + rank, print to terminal |
| `newsletter fetch` | Fetch only, print summary |
| `newsletter test-source <id>` | Debug a single source |
| `newsletter sources` | Show source status and health |
| `newsletter status` | Show system state (SQLite backend) |
| `newsletter history` | Browse past digests |
| `newsletter history --detail <ID>` | View a specific past digest |
| `newsletter install-schedule` | Install daily launchd/cron job |
| `newsletter install-schedule --uninstall` | Remove installed schedule |
| `newsletter re-enable <source>` | Reset error count for a source |

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
├── cli.py              # Click CLI (9 commands)
├── config.py           # Pydantic config
├── models.py           # Article, Priority, Digest, SourceHealth
├── pipeline.py         # Orchestrator (fetch → dedup → rank → deliver)
├── utils.py            # URL normalization, title similarity
├── scheduling.py       # LaunchAgent / crontab scheduling
├── sources/            # Source plugins (one per file)
├── ranking/            # Claude API ranking
├── delivery/           # Resend email + templates
└── state/              # SQLite persistence
```

## v2 Features

- **SQLite state**: Replaced JSON with SQLite (WAL mode). Auto-migrates from v1 `state.json` on first run.
- **Fuzzy dedup**: URL normalization (strips tracking params, www, trailing slash), title fingerprinting, cross-source title similarity matching (85% threshold).
- **Source health monitoring**: Auto-disables sources after 3 consecutive failures, retries after 24h cooldown. Use `re-enable` to reset manually.
- **Digest history**: Browse past digests with `--since`, `--until`, `--search`, and `--detail` options.
- **Scheduling**: Install a daily launchd plist (macOS) or crontab entry (Linux) with `install-schedule`.

## Adding a New Source

1. Create `src/newsletter_agent/sources/my_source.py` implementing `BaseSource`
2. Register in `sources/__init__.py` SOURCE_REGISTRY
3. Add config toggle in `config.py` SourcesConfig
4. Wire up instantiation in `sources/__init__.py` `instantiate_source()`

## License

MIT
