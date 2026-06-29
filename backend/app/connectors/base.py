from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Check whether the connector can reach and read the source."""

    @abstractmethod
    async def fetch_latest(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch latest normalized articles from the source."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return a lightweight connector health snapshot."""
