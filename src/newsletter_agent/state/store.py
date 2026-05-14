"""SQLite-backed state manager for v2."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from newsletter_agent.models import Article, Digest, SourceHealth
from newsletter_agent.utils import normalize_url, title_fingerprint

SCHEMA_VERSION = 2

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
    articles_json TEXT
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

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_seen_normalized ON seen_articles(normalized_url);
CREATE INDEX IF NOT EXISTS idx_seen_fingerprint ON seen_articles(title_fingerprint);
CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(date);
CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status);
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
        self._conn.commit()

    # --- Seen articles (dedup) ---

    def is_seen(self, url: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_articles WHERE url = ? OR normalized_url = ?",
            (url, normalize_url(url)),
        ).fetchone()
        return row is not None

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

    def prune_seen(self, max_age_days: int = 30) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM seen_articles WHERE first_seen < ?", (cutoff,),
        )
        return cursor.rowcount

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

    def get_all_source_health(self) -> list[SourceHealth]:
        rows = self._conn.execute("SELECT * FROM source_meta").fetchall()
        result = []
        for row in rows:
            result.append(SourceHealth(
                source_id=row["source_id"],
                last_fetch=_parse_dt(row["last_fetch"]),
                last_success=_parse_dt(row["last_success"]),
                consecutive_errors=row["consecutive_errors"] or 0,
                total_articles_fetched=row["total_articles_fetched"] or 0,
                last_error=row["last_error"],
                auto_disabled=bool(row["auto_disabled"]),
            ))
        return result

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

    def save_digest(self, digest: Digest) -> int:
        cursor = self._conn.execute(
            """INSERT INTO digests
               (date, sources_used, total_fetched, total_after_dedup,
                generation_time_seconds, email_sent, email_id, articles_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                digest.date.isoformat(),
                json.dumps(digest.sources_used),
                digest.total_fetched,
                digest.total_after_dedup,
                digest.generation_time_seconds,
                1 if digest.email_sent else 0,
                digest.email_id,
                json.dumps([a.model_dump(mode="json") for a in digest.articles]),
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

    # --- Batch jobs ---

    def save_batch_job(
        self,
        batch_id: str,
        articles: list[Article],
        interests: list[str],
    ) -> int:
        now = datetime.now(UTC).isoformat()
        cursor = self._conn.execute(
            """INSERT INTO batch_jobs
               (batch_id, status, created_at, articles_json, interests_json)
               VALUES (?, 'submitted', ?, ?, ?)""",
            (
                batch_id,
                now,
                json.dumps([a.model_dump(mode="json") for a in articles]),
                json.dumps(interests),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid or 0

    def get_pending_batch(self) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM batch_jobs WHERE status IN ('submitted', 'processing') "
            "ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        return dict(row) if row else None

    def update_batch_status(
        self,
        batch_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE batch_jobs SET status = ?, completed_at = ?, error = ?
               WHERE batch_id = ?""",
            (status, now if status == "ended" else None, error, batch_id),
        )
        self._conn.commit()

    def get_batch_articles(self, batch_id: str) -> list[Article]:
        row = self._conn.execute(
            "SELECT articles_json FROM batch_jobs WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if not row:
            return []
        return [
            Article.model_validate(a)
            for a in json.loads(row["articles_json"] or "[]")
        ]

    def get_batch_interests(self, batch_id: str) -> list[str]:
        row = self._conn.execute(
            "SELECT interests_json FROM batch_jobs WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if not row:
            return []
        return json.loads(row["interests_json"] or "[]")

    # --- General ---

    def save(self) -> None:
        self._set_meta("last_run", datetime.now(UTC).isoformat())
        self._conn.commit()

    def load(self) -> None:
        pass  # SQLite is always loaded

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


def _parse_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None
