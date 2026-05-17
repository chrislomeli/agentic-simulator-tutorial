"""
world-simulator.agents.logistics.tools.wildfires

Tool: get_wildfire_activity
───────────────────────────
Returns historical wildfire data filtered by acreage range.

Useful for logistics planning: "how many resources were deployed to
fires of similar size?" The agent queries past incidents to estimate
the scale of response needed for a new ignition.

Design notes
────────────
Thin query layer over the wildfire_activity table. The LLM specifies
acreage bounds to find comparable fires. Results include resource
counts (personnel, crews, engines, helicopters) deployed historically.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from stores.pg_gateway import PgGateway
from stores.wildfire_repo import WildfireRepository


# ═══════════════════════════════════════════════════════════════════════════════
# Output schema — what the tool returns to the LLM
# ═══════════════════════════════════════════════════════════════════════════════

class WildfireRecord(BaseModel):
    """A single historical wildfire incident with resource deployment counts."""

    imsr_date: Optional[date] = None
    fire_name: Optional[str] = None
    gacc: Optional[str] = None
    gacc_priority: Optional[int] = None
    fire_size_acres: Optional[int] = None
    percent_containment: Optional[int] = None
    personnel: Optional[int] = None
    crews: Optional[int] = None
    engines: Optional[int] = None
    helicopters: Optional[int] = None
    structures_lost: Optional[int] = None
    cost_to_date: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Tool factory
# ═══════════════════════════════════════════════════════════════════════════════

def make_get_wildfire_activity(pg_gateway: PgGateway):
    """Factory: closes over pg_gateway so the LLM only sees the query parameters."""

    repo = WildfireRepository(pg_gateway)

    @tool
    def get_wildfire_activity(
        min_acres: float = Field(description="Minimum fire size in acres (inclusive)."),
        max_acres: float = Field(description="Maximum fire size in acres (inclusive)."),
        top: int = Field(description="Return at most this many records, most recent first."),
    ) -> list[dict]:
        """Get historical wildfire incidents within an acreage range.

        Use this to benchmark how many crews, engines, and helicopters were
        historically deployed to fires of a similar size. Results are sorted
        most-recent first.
        """
        results = repo.fetch_similar_fires(
            min_acres=int(min_acres),
            max_acres=int(max_acres),
            limit=top,
        )
        return [WildfireRecord.model_validate(r.model_dump()).model_dump(exclude_none=True) for r in results]

    return get_wildfire_activity
