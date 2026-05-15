"""Mock wildfire repository — loads from wildfire_activity.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from stores.base import WildfireRepository as WildfireRepositoryBase
from stores.schemas import WildfireActivity

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "wildfire_activity.json"


def _load() -> list[WildfireActivity]:
    rows = json.loads(_DATA_FILE.read_text())
    for r in rows:
        # origin_ownership is typed int in the schema but seed data contains agency
        # string codes ('FS', 'ST', 'BLM', …) — coerce unknowns to None.
        oo = r.get("origin_ownership")
        if oo is not None and not isinstance(oo, int):
            try:
                r["origin_ownership"] = int(oo)
            except (ValueError, TypeError):
                r["origin_ownership"] = None
    return [WildfireActivity.model_validate(r) for r in rows]


class MockWildfireRepository(WildfireRepositoryBase):

    def fetch_similar_fires(
        self,
        min_acres: int,
        max_acres: int,
        limit: int = 10,
    ) -> list[WildfireActivity]:
        logger.info("Mock: fetching fires between %d and %d acres", min_acres, max_acres)
        results = [
            r for r in _load()
            if r.fire_size_acres is not None and min_acres <= r.fire_size_acres <= max_acres
        ]
        # Sort most-recent first (imsr_date descending)
        results.sort(key=lambda r: r.imsr_date or "0000-00-00", reverse=True)
        results = results[:limit]
        logger.info("Mock: found %d matching fires", len(results))
        return results

    def fetch_by_fire_name(self, fire_name: str, limit: int = 5) -> list[WildfireActivity]:
        needle = fire_name.lower()
        results = [
            r for r in _load()
            if r.fire_name and needle in r.fire_name.lower()
        ]
        results.sort(key=lambda r: r.imsr_date or "0000-00-00", reverse=True)
        results = results[:limit]
        logger.info("Mock: found %d fires matching %r", len(results), fire_name)
        return results
