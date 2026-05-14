"""JSON-file-backed state manager with atomic writes."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from newsletter_agent.models import Article, Digest


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"
        self.history_dir = self.state_dir / "history"
        self._state: dict[str, Any] = {}
        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        if self.state_file.exists():
            with open(self.state_file) as f:
                self._state = json.load(f)
        else:
            self._state = {
                "version": 1,
                "last_run": None,
                "sources": {},
                "seen_articles": {},
            }

    def save(self) -> None:
        self._state["last_run"] = datetime.now(UTC).isoformat()
        self._atomic_write(self.state_file, self._state)

    def is_seen(self, url: str) -> bool:
        return url in self._state.get("seen_articles", {})

    def mark_seen(self, article: Article) -> None:
        seen = self._state.setdefault("seen_articles", {})
        seen[article.url] = {
            "first_seen": datetime.now(UTC).isoformat(),
            "source_id": article.source_id,
            "title": article.title,
        }

    def update_source_meta(
        self,
        source_id: str,
        *,
        success: bool = True,
        articles_fetched: int = 0,
        error: str | None = None,
    ) -> None:
        sources = self._state.setdefault("sources", {})
        meta = sources.setdefault(source_id, {
            "last_fetch": None,
            "last_success": None,
            "consecutive_errors": 0,
            "total_articles_fetched": 0,
        })
        now = datetime.now(UTC).isoformat()
        meta["last_fetch"] = now
        if success:
            meta["last_success"] = now
            meta["consecutive_errors"] = 0
            total = meta.get("total_articles_fetched", 0)
            meta["total_articles_fetched"] = total + articles_fetched
        else:
            meta["consecutive_errors"] = meta.get("consecutive_errors", 0) + 1
            meta["last_error"] = error

    def get_source_meta(self, source_id: str) -> dict[str, Any]:
        return self._state.get("sources", {}).get(source_id, {})

    def save_digest(self, digest: Digest) -> None:
        filename = f"digest_{digest.date.strftime('%Y-%m-%d_%H%M%S')}.json"
        path = self.history_dir / filename
        self._atomic_write(path, digest.model_dump(mode="json"))

    def prune_seen(self, max_age_days: int = 30) -> int:
        seen = self._state.get("seen_articles", {})
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        to_remove = []
        for url, meta in seen.items():
            first_seen = meta.get("first_seen", "")
            try:
                if datetime.fromisoformat(first_seen) < cutoff:
                    to_remove.append(url)
            except (ValueError, TypeError):
                to_remove.append(url)
        for url in to_remove:
            del seen[url]
        return len(to_remove)

    @property
    def last_run(self) -> datetime | None:
        raw = self._state.get("last_run")
        if raw:
            return datetime.fromisoformat(raw)
        return None

    @property
    def seen_count(self) -> int:
        return len(self._state.get("seen_articles", {}))

    def _atomic_write(self, path: Path, data: Any) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except BaseException:
            os.unlink(tmp_path)
            raise
