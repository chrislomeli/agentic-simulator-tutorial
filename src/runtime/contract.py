"""runtime.contract — the transport-agnostic request/response shared by
every way of invoking the graph.

This is the single typed spine. The facade takes and returns these
objects; inbound adapters (FastAPI route, AgentCore entrypoint, local
main) and the consumer-side outbound port all marshal to/from these at
their edges only. It is owned by the orchestration side so transports
import it and never redefine it — that is what keeps the in-process,
HTTP, and AgentCore paths the same shape.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.commons.schemas import GridPosition
from agents.supervisor.state import RiskScore


class TriggerRequest(BaseModel):
    """One trigger: "these cells changed — process them."

    ``correlation_id`` exists so remote adapters can retry idempotently;
    the in-process adapter simply ignores it. ``cells`` are positions
    only — the world map is read by the facade, never carried here (the
    write side already committed it).
    """

    correlation_id: str
    cells: list[GridPosition]


class TriggerResult(BaseModel):
    """Structured outcome of one trigger's graph run.

    Mirrors the seam's ``SupervisorInvocation`` but is a serializable
    contract type (so HTTP/AgentCore adapters return the same shape the
    in-process caller gets).
    """

    correlation_id: str
    cluster_ids: list[str]
    cluster_score: dict[str, RiskScore]
    assessments_produced: int
