"""
ogar.agents.routing

Shared routing helper for LangGraph conditional edges.

Every router in this project makes the same error check:
  - status == ERROR  → log a warning, return END
  - otherwise        → return the caller-specified next node

`_route_base` encodes that once. Routers call it and add their own
logic on top (e.g., the ReAct loop router also inspects tool_calls).

Usage:
    def route_after_classify(state) -> str:
        return _route_base(state, next_node="report_findings")
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END

from agents.state_types import StatusValue

logger = logging.getLogger(__name__)


def _route_base(state: Any, *, next_node: str, on_completion: str = END) -> str:
    """
    Core routing logic shared across all agents.

    Parameters
    ----------
    state:         Pydantic BaseModel with .status and optionally .error_message
                   and an identifier field (cluster_id, workflow_id, or session_id).
    next_node:     Node to route to when status is still in-progress.
    on_completion: Node to route to when status is COMPLETED (default: END).
    """
    status = state.status

    if status == StatusValue.ERROR:
        agent_id = (
            getattr(state, "cluster_id", None)
            or getattr(state, "workflow_id", None)
            or getattr(state, "session_id", None)
            or "unknown"
        )
        error_msg = getattr(state, "error_message", None)
        logger.warning(
            "Routing to END due to error (id=%s, error=%s)", agent_id, error_msg
        )
        return END

    if status == StatusValue.COMPLETED:
        return on_completion

    return next_node
