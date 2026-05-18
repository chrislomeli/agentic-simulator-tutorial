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

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from agents.supervisor.state import RiskScore
from world.transport.schemas import SensorEvent


class TriggerRequest(BaseModel):
    """One trigger: "here are the sensor events — process them."

    Carries the raw ``events``, not changed-cell positions, on purpose.
    The DB is an *immutable seed*, so the graph side cannot re-read live
    world state from it; instead the facade folds these events onto its
    seed-hydrated world (snapshot + event replay). This is the principled
    payload-carrying trigger: the wire format follows where the fold runs
    (the graph side), which is what keeps the seed reproducible.

    ``correlation_id`` exists so remote adapters can retry idempotently;
    the in-process adapter simply ignores it.
    """

    correlation_id: str
    events: list[SensorEvent]


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


@runtime_checkable
class GraphClient(Protocol):
    """Transport-agnostic outbound port: trigger in, result out.

    Lives here, with the contract types, not next to the in-process
    adapter — the port *is* part of the spine. Every caller (the
    streaming consumer, ``main``, a future API) depends on this Protocol;
    the deployment profile binds the adapter (in-process / HTTP /
    AgentCore). Defined here also keeps the consumer free of any import
    cycle through the facade.
    """

    async def invoke(self, request: TriggerRequest) -> TriggerResult: ...
