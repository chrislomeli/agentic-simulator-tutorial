"""
world-simulator.tools.advisory

Dispatch function for writing a ResourceAdvisory to the database.

Called directly from the extract_plan node after the structured-output step
produces a LogisticsAssessment. The graph decides whether to dispatch;
the agent no longer calls this as a tool.
"""

from __future__ import annotations

import logging

from agents.commons.schemas import Colors, ResourceAdvisory, ResourceAdvisoryRecord
from stores.base import AdvisoryRepository

logger = logging.getLogger(__name__)


def dispatch_advisory(advisory: ResourceAdvisory, repo: AdvisoryRepository) -> None:
    """Write a ResourceAdvisory to the database and log it."""
    logger.warning(
        "Advisory dispatched row=%d, col=%d",
        advisory.epicenter_row,
        advisory.epicenter_column,
        extra={"row": advisory.epicenter_row, "col": advisory.epicenter_column},
    )
    db_advisory = ResourceAdvisoryRecord(**advisory.model_dump())
    print(
        f"\n{Colors.RED}● ADVISORY DISPATCHED  row={advisory.epicenter_row},"
        f" col={advisory.epicenter_column}{Colors.RESET}"
    )
    repo.save_advisory(db_advisory)
