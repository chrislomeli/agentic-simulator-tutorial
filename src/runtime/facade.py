"""runtime.facade — the application service: turn a trigger (a list of
changed cells) into a graph run, returning a typed result.

This is the single home of "trigger → graph". Every inbound transport
(local main, FastAPI route, AgentCore entrypoint) is a thin adapter over
``GraphFacade.run_trigger``; nothing duplicates this logic.

Two phases, deliberately separated:
  - construction (once): hold the compiled graph + CellStateManager.
  - run_trigger (per trigger): read the world for the changed cells,
    build the per-cluster payload, invoke the graph.

``run_trigger`` mirrors the streaming orchestrator's invoke path exactly
(``readings_for`` → ``mark_cells_evaluated`` → ``invoke_supervisor_for_trigger``)
so behaviour is identical whether a trigger arrives via the stream loop
or via this facade. The world map is *not* passed in — it is read here
and reaches the graph nodes via dependency injection at build time.
"""

from __future__ import annotations

import logging

from agents.supervisor.state import SupervisorGraph
from runtime.contract import TriggerRequest, TriggerResult
from runtime.orchestrator import invoke_supervisor_for_trigger
from world.cell_state_manager import CellStateManager

logger = logging.getLogger(__name__)


class GraphFacade:
    """Directly-callable service over the supervisor graph.

    Built once at startup; ``run_trigger`` is the per-trigger entry point.
    """

    def __init__(
        self,
        *,
        supervisor_graph: SupervisorGraph,
        cell_state_manager: CellStateManager,
    ) -> None:
        self._graph = supervisor_graph
        self._manager = cell_state_manager

    async def run_trigger(self, request: TriggerRequest) -> TriggerResult:
        """Read the world for the changed cells and run the graph.

        Returns an empty result (no graph invocation) when none of the
        requested cells have readings — same short-circuit the streaming
        loop applies when its coalesced payload is empty.
        """
        positions: set[tuple[int, int]] = {(c.row, c.col) for c in request.cells}
        payload = self._manager.readings_for(positions=positions)

        included: set[tuple[int, int]] = set()
        for readings in payload.values():
            for r in readings:
                included.add((r.position.row, r.position.col))
        self._manager.mark_cells_evaluated(included)

        if not payload:
            logger.info(
                "Trigger %s: no readings for %d requested cell(s) — graph not invoked",
                request.correlation_id,
                len(request.cells),
            )
            return TriggerResult(
                correlation_id=request.correlation_id,
                cluster_ids=[],
                cluster_score={},
                assessments_produced=0,
            )

        outcome = await invoke_supervisor_for_trigger(self._graph, payload)
        return TriggerResult(
            correlation_id=request.correlation_id,
            cluster_ids=outcome.cluster_ids,
            cluster_score=outcome.cluster_score,
            assessments_produced=outcome.assessments_produced,
        )
