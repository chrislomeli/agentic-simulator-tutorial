"""
world-simulator.agents.logistics.tools.resources

Tool: get_resources_within
──────────────────────────
Lets the logistics LLM ask: "what crews/engines are reachable within
N miles of cell (row, col)?"

The tool converts grid coordinates to lat/long via the terrain table,
then queries all resources within the radius. Results include each
resource's current commitment status and, if committed, the fire it is
assigned to.

Design notes
────────────
The tool does NOT decide what resources are needed — that is the LLM's
job. It only reports what is available and reachable. Travel time is
straight-line distance (road-network routing would live in the repo).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict

from stores.pg_gateway import PgGateway
from stores.resources_repo import TranscriptRepository
from stores.terrain_repo import TerrainRepository


# ═══════════════════════════════════════════════════════════════════════════════
# Output schemas — what the tool returns to the LLM
# ═══════════════════════════════════════════════════════════════════════════════

class FireBriefing(BaseModel):
    """Fire details for a resource that is currently committed."""

    model_config = ConfigDict(populate_by_name=True)

    fire_id: str
    fire_name: Optional[str] = None
    fire_size_acres: Optional[int] = None
    percent_containment: Optional[int] = None
    gacc_priority: Optional[int] = None
    personnel: Optional[int] = None
    crews: Optional[int] = None
    engines: Optional[int] = None
    helicopters: Optional[int] = None
    structures_lost: Optional[int] = None


class ResourceCommitment(BaseModel):
    """A resource with its availability status and optional fire assignment."""

    model_config = ConfigDict(populate_by_name=True)

    resource_id: int
    resource_category: Optional[str] = None
    resource_type: Optional[str] = None
    nwcg_type: Optional[str] = None
    personnel: Optional[int] = None
    battalion: Optional[str] = None
    station_name: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    distance_miles: float

    status: str  # "available" or "committed"
    commitment_level: Optional[str] = None
    commitment_start_date: Optional[date] = None
    commitment_length_days: Optional[int] = None
    fire: Optional[FireBriefing] = None  # populated only when status == "committed"


# ═══════════════════════════════════════════════════════════════════════════════
# Tool factory
# ═══════════════════════════════════════════════════════════════════════════════

def make_get_resources_within(pg_gateway: PgGateway):
    """Factory: closes over pg_gateway so the LLM only sees the query parameters."""

    terrain_repo = TerrainRepository(pg_gateway)
    resources_repo = TranscriptRepository(pg_gateway)

    @tool
    def get_resources_within(cell_row: int, cell_col: int, max_distance_mi: float) -> dict:
        """Get all firefighting resources within a radius of a grid cell.

        Returns available and committed resources sorted by distance. For
        committed resources, includes the fire they are currently assigned to
        so the LLM can weigh whether to request reassignment.

        Args:
            cell_row: Grid row of the ignition cell (0-indexed, north=0).
            cell_col: Grid column of the ignition cell (0-indexed, west=0).
            max_distance_mi: Search radius in miles.
        """
        location = terrain_repo.fetch_cell_location(cell_row, cell_col)
        if location is None:
            return {"error": f"Cell ({cell_row}, {cell_col}) not found in terrain table."}

        lat, long = location
        rows = resources_repo.fetch_resources_with_commitments(lat, long, max_distance_mi)

        resources: list[dict] = []
        for r in rows:
            fire = None
            if r.get("fire_id") is not None:
                fire = FireBriefing(
                    fire_id=str(r["fire_id"]),
                    fire_name=r.get("fire_name"),
                    fire_size_acres=r.get("fire_size_acres"),
                    percent_containment=r.get("percent_containment"),
                    gacc_priority=r.get("gacc_priority"),
                    personnel=r.get("fire_personnel"),
                    crews=r.get("crews"),
                    engines=r.get("engines"),
                    helicopters=r.get("helicopters"),
                    structures_lost=r.get("structures_lost"),
                )

            resource = ResourceCommitment(
                resource_id=r["resource_id"],
                resource_category=r.get("resource_category"),
                resource_type=r.get("resource_type"),
                nwcg_type=r.get("nwcg_type"),
                personnel=r.get("personnel"),
                battalion=r.get("battalion"),
                station_name=r.get("station_name"),
                lat=r.get("lat"),
                long=r.get("long"),
                distance_miles=r["distance_miles"],
                status=r["status"],
                commitment_level=str(r["commitment_level"]) if r.get("commitment_level") else None,
                commitment_start_date=r.get("commitment_start_date"),
                commitment_length_days=r.get("commitment_length_days"),
                fire=fire,
            )
            resources.append(resource.model_dump(exclude_none=True))

        return {"resources": resources, "total": len(resources)}

    return get_resources_within
