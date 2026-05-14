"""Mock advisory repository — in-memory store, no persistence."""

from __future__ import annotations

import logging
from typing import Any

from stores.base import AdvisoryRepository as AdvisoryRepositoryBase

logger = logging.getLogger(__name__)


class MockAdvisoryRepository(AdvisoryRepositoryBase):

    def __init__(self) -> None:
        self._store: list[Any] = []

    def save_advisory(self, advisory: Any) -> int:
        return self.save_advisories([advisory])

    def save_advisories(self, advisories: list[Any]) -> int:
        self._store.extend(advisories)
        logger.info("Mock: saved %d advisories (total: %d)", len(advisories), len(self._store))
        return len(advisories)

    def fetch_recent_advisories(
        self,
        grid_row: int,
        grid_col: int,
        limit: int = 10,
    ) -> list[Any]:
        matches = [
            a for a in self._store
            if getattr(a, "epicenter_row", None) == grid_row
            and getattr(a, "epicenter_column", None) == grid_col
        ]
        results = list(reversed(matches))[:limit]
        logger.info(
            "Mock: fetched %d advisories for cell (%d, %d)",
            len(results),
            grid_row,
            grid_col,
        )
        return results
