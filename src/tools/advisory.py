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

from langchain_core.tools import tool

from agents.commons.schemas import Colors, ResourceAdvisory, ResourceAdvisoryRecord
from stores.base import AdvisoryRepository

logger = logging.getLogger(__name__)  # One per module


def make_send_advisory(repo: AdvisoryRepository):
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
            logger.warning(
                "Advisory sent row=%d, col=%d",
                advisory.epicenter_row,
                advisory.epicenter_column,
                extra={"row": advisory.epicenter_row, "col": advisory.epicenter_column},
            )

            db_advisory = ResourceAdvisoryRecord(**advisory.model_dump())

            print(
                f"\n{Colors.RED}● SEND ADVISORY  row={advisory.epicenter_row}, col={advisory.epicenter_column}{Colors.RESET}"
            )
            repo.save_advisory(db_advisory)

            return {"status": "ok"}

        except Exception as e:
            logger.error("Failed to send advisory: %s", e)
            return {"status": "error"}

    return send_advisory
