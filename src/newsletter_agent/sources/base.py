"""Abstract base class for all source plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from newsletter_agent.models import Article


class BaseSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable source name."""
        ...

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Machine identifier used in config and state."""
        ...

    @abstractmethod
    async def fetch(self, since: datetime | None = None) -> list[Article]:
        """Fetch new articles from this source."""
        ...

    def is_available(self) -> bool:
        """Check if this source has required config/credentials."""
        return True
