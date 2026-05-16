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

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agents.commons.schemas import Colors
from stores.base import WildfireRepository

# ═══════════════════════════════════════════════════════════════════════════════
# Output schema — what the tool returns to the LLM
# ═══════════════════════════════════════════════════════════════════════════════


class WildfireRecord(BaseModel):
    """A single historical wildfire incident with resource deployment counts."""

    imsr_date: date | None = None
    fire_name: str | None = None
    gacc: str | None = None
    gacc_priority: int | None = None
    fire_size_acres: int | None = None
    percent_containment: int | None = None
    personnel: int | None = None
    crews: int | None = None
    engines: int | None = None
    helicopters: int | None = None
    structures_lost: int | None = None
    cost_to_date: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Tool factory
# ═══════════════════════════════════════════════════════════════════════════════


def make_get_wildfire_activity(repo: WildfireRepository):
    """Factory: closes over the wildfire repo so the LLM only sees the query parameters."""

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
        print(
            f"\n{Colors.TEAL}● TOOL get_resources_within min_acres={min_acres},max_acres={max_acres} limit={top}{Colors.RESET}"
        )
        results = repo.fetch_similar_fires(
            min_acres=int(min_acres),
            max_acres=int(max_acres),
            limit=top,
        )
        return [
            WildfireRecord.model_validate(r.model_dump()).model_dump(exclude_none=True)
            for r in results
        ]

    return get_wildfire_activity
