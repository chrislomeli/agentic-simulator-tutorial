"""
world-simulator.agents.logistics.tools.advisory

Tool: send_advisory
───────────────────
Allows the logistics agent to send structured resource advisories to
field commanders or upstream dispatch.

Advisories communicate: location, situation urgency, edge-case risks,
and specific recommendations. The structured format supports both human
readability and downstream automation (alerting, resource pre-positioning).

Design notes
────────────
Pure output tool — no external dependencies. The advisory is validated,
logged, and returned. In production this could publish to a message bus
or incident management system.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4, UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from stores import PgGateway
from stores.advisory_repo import ResourceAdvisoryRepository

logger = logging.getLogger(__name__)  # One per module

# Agent view of a published advisory
class ResourceAdvisory(BaseModel):
    """Structured advisory report for resource deployment decisions."""
    epicenter_row: int = Field(
        description="Terrain grid row index of the fire risk epicenter (highest-risk cell)."
    )

    epicenter_column: int = Field(
        description="Terrain grid column index of the fire risk epicenter (highest-risk cell)."
    )

    location_description: str = Field(
        description="Human-readable description of the affected area, especially for impact zones difficult to describe in grid coordinates (e.g., 'northwest slope below ridgeline')."
    )
    situation: str = Field(
        description="Current fire status, spread direction, and immediate threat level. 1-2 sentences."
    )

    urgency_level: int = Field(
        ge=1,
        le=4,
        description="""How urgent and immediate is this situation?

LEVEL 4 (Fade Out): Lowest readiness; routine monitoring.
LEVEL 3 (Double Take): Elevated readiness; increased monitoring.
LEVEL 2 (Fast Pace): High readiness; prepare for deployment.
LEVEL 1 (Cocked Pistol): Maximum readiness; imminent response required.
"""
    )
    notes: str = Field(
        description=(
            "Context, uncertainties, and edge-case reasoning. "
            "Discuss resource conflicts, conditional scenarios, or cascading risks. "
            "Example: '3 engines committed to 30%-contained Lompoc fire. "
            "If 2+ hotspots ignite simultaneously, Level 1 capacity exceeded.'"
        )
    )
    recommendation: str = Field(
        description="Specific action to take, or 'Monitor only' if no deployment needed."
    )

# Database view of the ResourceAdvisory adds tracking fields
class ResourceAdvisoryRecord(ResourceAdvisory):
    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier. Generated on creation."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: Literal["SENT", "SUPPRESSED", "ACKNOWLEDGED"] = Field(
        default="SENT"
    )

    def to_db_row(self) -> tuple:
        """Return tuple for INSERT/UPDATE — computed fields excluded."""
        return (
            self.id,
            self.created_at,
            self.status,
            self.epicenter_row,
            self.epicenter_column,
            self.location_description,
            self.situation,
            self.urgency_level,
            self.notes,
            self.recommendation,
        )


def make_send_advisory(pg_gateway: PgGateway):
    """Factory: creates the send_advisory tool."""

    @tool
    def send_advisory(advisory: ResourceAdvisory) -> dict:
        """Send a structured resource advisory.

        Use this to communicate resource constraints, fire risk escalations,
        or deployment recommendations to field command or dispatch centers.

        Advisories are warranted when:
        - Fire risk exceeds resource availability
        - Prior commitments limit response capacity
        - Human life or critical property is at risk
        - Burnable acreage threatens containment

        Returns:
            {"status": "ok"} on successful transmission
        """
        try:
            RED, RESET = "\033[31m", "\033[0m"
            print(f"\n{RED}● ADVISORY SENT {RESET}")

            repo = ResourceAdvisoryRepository(pg_gateway)

            db_advisory = ResourceAdvisoryRecord(
                **advisory.model_dump()
            )

            repo.save_advisory(db_advisory)

            return {"status": "ok"}

        except Exception as e:
            logger.error("Failed to send advisory: %s", e)
            return {"status": "error"}

    return send_advisory
