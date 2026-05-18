"""runtime.graph_client — the consumer's outbound port to the graph.

The CQRS write-side consumer, after committing the world update, must
*call* the graph layer. It depends only on the ``GraphClient`` Protocol;
the deployment wires in an adapter:

  - in-process (this module): call the facade directly — laptop / single
    binary, where consumer and graph share a process.
  - HTTP (future): POST to the FastAPI route.
  - AgentCore (future): ``InvokeAgentRuntime``.

A future adapter is just another implementation of this Protocol over the
same ``runtime.contract`` types — the consumer code never changes across
deployments. The port is ``async`` and its contract is shaped for the
*remote* case (idempotent retry via ``TriggerRequest.correlation_id``);
the in-process adapter is simply the trivially-reliable implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from runtime.contract import TriggerRequest, TriggerResult
from runtime.facade import GraphFacade


@runtime_checkable
class GraphClient(Protocol):
    """Transport-agnostic outbound port: trigger in, result out."""

    async def invoke(self, request: TriggerRequest) -> TriggerResult: ...


class InProcessGraphClient:
    """In-process adapter — delegates straight to the facade, no transport.

    The single-process binding of ``GraphClient``. A FastAPI or AgentCore
    adapter would implement the same Protocol with a network hop; the
    consumer cannot tell the difference.
    """

    def __init__(self, facade: GraphFacade) -> None:
        self._facade = facade

    async def invoke(self, request: TriggerRequest) -> TriggerResult:
        return await self._facade.run_trigger(request)
