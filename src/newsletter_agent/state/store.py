"""SQLite-backed state manager for v2."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from newsletter_agent.models import Article, Digest
from newsletter_agent.utils import normalize_url, title_fingerprint

SCHEMA_VERSION = 3

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS seen_articles (
    url TEXT PRIMARY KEY,
    normalized_url TEXT,
    title TEXT,
    title_fingerprint TEXT,
    source_id TEXT,
    first_seen TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_meta (
    source_id TEXT PRIMARY KEY,
    last_fetch TIMESTAMP,
    last_success TIMESTAMP,
    consecutive_errors INTEGER DEFAULT 0,
    total_articles_fetched INTEGER DEFAULT 0,
    last_error TEXT,
    auto_disabled INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TIMESTAMP,
    sources_used TEXT,
    total_fetched INTEGER,
    total_after_dedup INTEGER,
    generation_time_seconds REAL,
    email_sent INTEGER DEFAULT 0,
    email_id TEXT,
    articles_json TEXT,
    cost_breakdown TEXT
);

CREATE TABLE IF NOT EXISTS batch_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT UNIQUE,
    status TEXT DEFAULT 'submitted',
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    articles_json TEXT,
    interests_json TEXT,
    digest_id INTEGER,
    error TEXT
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    feed_url TEXT,
    type TEXT NOT NULL,
    source_type TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    discovered_by TEXT NOT NULL DEFAULT 'user',
    added_at TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
    content_hash TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_seen_normalized ON seen_articles(normalized_url);
CREATE INDEX IF NOT EXISTS idx_seen_fingerprint ON seen_articles(title_fingerprint);
CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(date);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status);
CREATE INDEX IF NOT EXISTS idx_resources_source_type ON resources(source_type);
CREATE INDEX IF NOT EXISTS idx_resources_enabled ON resources(enabled);
"""


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.db_path = self.state_dir / "newsletter.db"
        self._ensure_dirs()
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()
        self._maybe_migrate_from_json()

    def _ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _init_db(self) -> None:
        self._conn.executescript(CREATE_TABLES)
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        cursor = self._conn.execute("PRAGMA table_info(digests)")
        columns = {row[1] for row in cursor.fetchall()}
        if "cost_breakdown" not in columns:
            self._conn.execute(
                "ALTER TABLE digests ADD COLUMN cost_breakdown TEXT",
            )

    # --- Resources ---

    def get_resources(
        self,
        source_type: str | None = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM resources"
        conditions = []
        params: list[Any] = []
        if source_type is not None:
            conditions.append("source_type = ?")
            params.append(source_type)
        if enabled_only:
            conditions.append("enabled = 1")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY name"
        return [dict(row) for row in self._conn.execute(query, params).fetchall()]

    def get_all_resources(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM resources ORDER BY source_type, name",
            ).fetchall()
        ]

    def get_rss_feeds(self) -> dict[str, str]:
        rows = self.get_resources(source_type="rss")
        return {row["name"]: (row["feed_url"] or row["url"]) for row in rows}

    def get_subreddits(self) -> list[str]:
        rows = self.get_resources(source_type="reddit")
        return [row["name"].removeprefix("r/") for row in rows]

    def get_web_pages(self) -> dict[str, str]:
        rows = self.get_resources(source_type="web")
        return {row["name"]: row["url"] for row in rows}

    def add_resource(
        self,
        name: str,
        url: str,
        *,
        feed_url: str | None = None,
        resource_type: str = "other",
        source_type: str | None = None,
        discovered_by: str = "user",
        description: str = "",
    ) -> int | None:
        try:
            cursor = self._conn.execute(
                """INSERT INTO resources
                   (name, url, feed_url, type, source_type, enabled,
                    discovered_by, added_at, description)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    name, url, feed_url, resource_type, source_type,
                    discovered_by, datetime.now(UTC).isoformat(), description,
                ),
            )
            self._conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def remove_resource(self, resource_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM resources WHERE id = ?", (resource_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def resource_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM resources").fetchone()
        return row[0] if row else 0

    # --- Seen articles (dedup) ---

    def is_seen_normalized(self, normalized: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_articles WHERE normalized_url = ?",
            (normalized,),
        ).fetchone()
        return row is not None

    def find_similar_title(self, fp: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_articles WHERE title_fingerprint = ?",
            (fp,),
        ).fetchone()
        return row is not None

    def mark_seen(self, article: Article) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO seen_articles
               (url, normalized_url, title, title_fingerprint, source_id, first_seen)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                article.url,
                article.normalized_url,
                article.title,
                article.title_fp,
                article.source_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    # --- Source health ---

    def update_source_meta(
        self,
        source_id: str,
        *,
        success: bool = True,
        articles_fetched: int = 0,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        existing = self._conn.execute(
            "SELECT * FROM source_meta WHERE source_id = ?", (source_id,),
        ).fetchone()

        if existing is None:
            self._conn.execute(
                """INSERT INTO source_meta
                   (source_id, last_fetch, last_success, consecutive_errors,
                    total_articles_fetched, last_error, auto_disabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id, now,
                    now if success else None,
                    0 if success else 1,
                    articles_fetched if success else 0,
                    None if success else error,
                    0,
                ),
            )
        elif success:
            self._conn.execute(
                """UPDATE source_meta SET
                   last_fetch = ?, last_success = ?, consecutive_errors = 0,
                   total_articles_fetched = total_articles_fetched + ?,
                   auto_disabled = 0
                   WHERE source_id = ?""",
                (now, now, articles_fetched, source_id),
            )
        else:
            new_errors = (existing["consecutive_errors"] or 0) + 1
            self._conn.execute(
                """UPDATE source_meta SET
                   last_fetch = ?, consecutive_errors = ?, last_error = ?
                   WHERE source_id = ?""",
                (now, new_errors, error, source_id),
            )

    def get_source_meta(self, source_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM source_meta WHERE source_id = ?", (source_id,),
        ).fetchone()
        if row is None:
            return {}
        return dict(row)

    def is_source_healthy(
        self, source_id: str, max_failures: int = 3, retry_after_hours: int = 24,
    ) -> bool:
        meta = self.get_source_meta(source_id)
        if not meta:
            return True
        errors = meta.get("consecutive_errors", 0)
        if errors < max_failures:
            return True
        # Allow retry after cooldown
        last_fetch = _parse_dt(meta.get("last_fetch"))
        if last_fetch:
            cooldown = datetime.now(UTC) - timedelta(hours=retry_after_hours)
            if last_fetch < cooldown:
                return True
        return False

    def reset_source_errors(self, source_id: str) -> bool:
        cursor = self._conn.execute(
            """UPDATE source_meta SET consecutive_errors = 0, auto_disabled = 0
               WHERE source_id = ?""",
            (source_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # --- Digests ---

    def save_digest(self, digest: Digest, cost_breakdown: str = "") -> int:
        cursor = self._conn.execute(
            """INSERT INTO digests
               (date, sources_used, total_fetched, total_after_dedup,
                generation_time_seconds, email_sent, email_id, articles_json,
                cost_breakdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                digest.date.isoformat(),
                json.dumps(digest.sources_used),
                digest.total_fetched,
                digest.total_after_dedup,
                digest.generation_time_seconds,
                1 if digest.email_sent else 0,
                digest.email_id,
                json.dumps([a.model_dump(mode="json") for a in digest.articles]),
                cost_breakdown,
            ),
        )
        return cursor.lastrowid or 0

    def update_digest_email(self, digest_id: int, email_id: str) -> None:
        self._conn.execute(
            "UPDATE digests SET email_sent = 1, email_id = ? WHERE id = ?",
            (email_id, digest_id),
        )
        self._conn.commit()

    def get_digest_history(
        self,
        limit: int = 10,
        offset: int = 0,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT id, date, sources_used, total_fetched, total_after_dedup, "
        query += "generation_time_seconds, email_sent, articles_json FROM digests"
        conditions = []
        params: list[Any] = []
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from.isoformat())
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to.isoformat())
        if search:
            conditions.append("articles_json LIKE ?")
            params.append(f"%{search}%")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            articles = json.loads(row["articles_json"] or "[]")
            critical_count = sum(
                1 for a in articles
                if a.get("priority") == "CRITICAL - ACT NOW"
            )
            results.append({
                "id": row["id"],
                "date": row["date"],
                "total_fetched": row["total_fetched"],
                "total_after_dedup": row["total_after_dedup"],
                "article_count": len(articles),
                "critical_count": critical_count,
                "email_sent": bool(row["email_sent"]),
                "generation_time": row["generation_time_seconds"],
            })
        return results

    def get_digest_by_id(self, digest_id: int) -> Digest | None:
        row = self._conn.execute(
            "SELECT * FROM digests WHERE id = ?", (digest_id,),
        ).fetchone()
        if row is None:
            return None
        from newsletter_agent.models import Article

        articles = [
            Article.model_validate(a)
            for a in json.loads(row["articles_json"] or "[]")
        ]
        return Digest(
            digest_id=row["id"],
            date=datetime.fromisoformat(row["date"]),
            articles=articles,
            sources_used=json.loads(row["sources_used"] or "[]"),
            total_fetched=row["total_fetched"],
            total_after_dedup=row["total_after_dedup"],
            generation_time_seconds=row["generation_time_seconds"],
            email_sent=bool(row["email_sent"]),
            email_id=row["email_id"],
        )

    def get_digest_cost(self, digest_id: int) -> str:
        try:
            row = self._conn.execute(
                "SELECT cost_breakdown FROM digests WHERE id = ?", (digest_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return ""
        if row is None:
            return ""
        return row["cost_breakdown"] or ""

    # --- General ---

    def save(self) -> None:
        self._set_meta("last_run", datetime.now(UTC).isoformat())
        self._conn.commit()

    @property
    def last_run(self) -> datetime | None:
        val = self._get_meta("last_run")
        return datetime.fromisoformat(val) if val else None

    @property
    def seen_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM seen_articles").fetchone()
        return row[0] if row else 0

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,),
        ).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )

    # --- JSON migration ---

    def _maybe_migrate_from_json(self) -> None:
        json_state = self.state_dir / "state.json"
        if not json_state.exists():
            return
        # Only migrate if DB is empty
        row = self._conn.execute("SELECT COUNT(*) FROM seen_articles").fetchone()
        if row and row[0] > 0:
            return

        with open(json_state) as f:
            state = json.load(f)

        # Migrate seen articles
        for url, meta in state.get("seen_articles", {}).items():
            self._conn.execute(
                """INSERT OR IGNORE INTO seen_articles
                   (url, normalized_url, title, title_fingerprint,
                    source_id, first_seen)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    url,
                    normalize_url(url),
                    meta.get("title", ""),
                    title_fingerprint(meta.get("title", "")),
                    meta.get("source_id", ""),
                    meta.get("first_seen", datetime.now(UTC).isoformat()),
                ),
            )

        # Migrate source metadata
        for source_id, meta in state.get("sources", {}).items():
            self._conn.execute(
                """INSERT OR IGNORE INTO source_meta
                   (source_id, last_fetch, last_success, consecutive_errors,
                    total_articles_fetched, last_error)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    source_id,
                    meta.get("last_fetch"),
                    meta.get("last_success"),
                    meta.get("consecutive_errors", 0),
                    meta.get("total_articles_fetched", 0),
                    meta.get("last_error"),
                ),
            )

        if state.get("last_run"):
            self._set_meta("last_run", state["last_run"])

        self._conn.commit()

        # Migrate digest history files
        history_dir = self.state_dir / "history"
        if history_dir.exists():
            for digest_file in sorted(history_dir.glob("digest_*.json")):
                try:
                    with open(digest_file) as f:
                        d = json.load(f)
                    self._conn.execute(
                        """INSERT INTO digests
                           (date, sources_used, total_fetched, total_after_dedup,
                            generation_time_seconds, articles_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            d.get("date", ""),
                            json.dumps(d.get("sources_used", [])),
                            d.get("total_fetched", 0),
                            d.get("total_after_dedup", 0),
                            d.get("generation_time_seconds", 0),
                            json.dumps(d.get("articles", [])),
                        ),
                    )
                except (json.JSONDecodeError, KeyError):
                    continue
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- Embedding cache ---

    def get_cached_embedding(self, content_hash: str) -> bytes | None:
        row = self._conn.execute(
            "SELECT embedding FROM embeddings WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return row["embedding"] if row else None

    def cache_embedding(self, content_hash: str, embedding: bytes) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings (content_hash, embedding) VALUES (?, ?)",
            (content_hash, embedding),
        )
        self._conn.commit()


def _parse_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None
