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

# The GraphClient Protocol lives with the contract types (the spine), not
# here next to the adapters. Re-exported so existing
# ``from runtime.graph_client import GraphClient`` imports keep working.
from runtime.contract import GraphClient as GraphClient
from runtime.contract import TriggerRequest, TriggerResult
from runtime.facade import GraphFacade


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


# ── Remote adapters (stubs) ──────────────────────────────────────────────────
#
# These are the k8s-deployed / aws bindings of the same port: the consumer
# and the graph run in separate containers, so ``invoke`` is a network hop
# instead of a direct call. They are deliberately named, Protocol-shaped
# stubs — the seam and the profile wiring are real and type-check today;
# only the transport body is deferred to the API step (where the FastAPI
# route / AgentCore handler that answers these calls is built). No consumer
# code changes when they are filled in: it depends on ``GraphClient``.


class HttpGraphClient:
    """HTTP adapter — POSTs the trigger to the FastAPI graph service.

    Stub: the FastAPI route it calls is built in the API step.
    """

    def __init__(self, *, base_url: str, timeout_s: float = 30.0) -> None:
        self._base_url = base_url
        self._timeout_s = timeout_s

    async def invoke(self, request: TriggerRequest) -> TriggerResult:
        raise NotImplementedError(
            "HttpGraphClient is a stub. The FastAPI graph route it POSTs to "
            "is built in the API step; the consumer does not change when it "
            "lands (it depends on the GraphClient Protocol). Use "
            "InProcessGraphClient for the local/collapsed profiles."
        )


class AgentCoreGraphClient:
    """AWS Bedrock AgentCore adapter — ``InvokeAgentRuntime`` over the port.

    Stub: the AgentCore handler that wraps the facade is built in the API
    step. Kept here so the aws profile can wire a real, typed adapter.
    """

    def __init__(self, *, agent_runtime_arn: str, region: str | None = None) -> None:
        self._arn = agent_runtime_arn
        self._region = region

    async def invoke(self, request: TriggerRequest) -> TriggerResult:
        raise NotImplementedError(
            "AgentCoreGraphClient is a stub. The Bedrock AgentCore handler "
            "that answers this is built in the API step; the consumer does "
            "not change when it lands (it depends on the GraphClient "
            "Protocol)."
        )
