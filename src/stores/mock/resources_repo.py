"""Mock resource repository — loads from resources.json, no PostGIS required.

fetch_resources_with_commitments filters by haversine distance and returns
every resource as 'available' (no resource_assignments table in mock mode).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from stores.base import ResourceRepository as ResourceRepositoryBase
from stores.schemas import Resource

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "resources.json"


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _load() -> list[dict]:
    return json.loads(_DATA_FILE.read_text())


class MockResourceRepository(ResourceRepositoryBase):
    def __init__(self) -> None:
        self._saved: list[Resource] = []

    def save_collection(self, resources: list[Resource]) -> int:
        self._saved.extend(resources)
        return len(resources)

    def fetch_resources_with_commitments(
        self,
        lat: float,
        long: float,
        radius_miles: float,
    ) -> list[dict]:
        logger.info(
            "Mock: fetching resources within %.1f miles of (%.4f, %.4f)",
            radius_miles,
            lat,
            long,
        )

        results = []
        for row in _load():
            r_lat = row.get("lat")
            r_lon = row.get("long")
            if r_lat is None or r_lon is None:
                continue

            dist = _haversine_miles(lat, long, r_lat, r_lon)
            if dist > radius_miles:
                continue

            results.append(
                {
                    "resource_id": row.get("resource_id"),
                    "resource_category": row.get("resource_category"),
                    "resource_type": row.get("resource_type"),
                    "nwcg_type": row.get("nwcg_type"),
                    "personnel": row.get("personnel"),
                    "battalion": row.get("battalion"),
                    "station_name": row.get("station_name"),
                    "lat": r_lat,
                    "long": r_lon,
                    "distance_miles": round(dist, 2),
                    "status": "available",
                    # Commitment fields — always None in mock (no resource_assignments table)
                    "commitment_level": None,
                    "commitment_start_date": None,
                    "commitment_length_days": None,
                    "fire_id": None,
                    "fire_name": None,
                    "fire_size_acres": None,
                    "percent_containment": None,
                    "gacc_priority": None,
                    "fire_personnel": None,
                    "crews": None,
                    "engines": None,
                    "helicopters": None,
                    "structures_lost": None,
                }
            )

        results.sort(key=lambda r: r["distance_miles"])
        logger.info("Mock: found %d resources within radius", len(results))
        return results
