"""runtime.facade — the application service: turn a trigger (a batch of
sensor events) into a graph run, returning a typed result.

This is the single home of "trigger → graph". Every inbound transport
(local main, FastAPI route, AgentCore entrypoint) is a thin adapter over
``GraphFacade.run_trigger``; nothing duplicates this logic.

The fold lives here, on the graph side
──────────────────────────────────────
The facade owns a ``CellStateManager`` hydrated once from the *immutable
DB seed*. Each trigger folds its events onto that in-memory world
(snapshot + event replay), so the seed is never mutated and scenarios
replay identically. The consumer is a thin bridge that just forwards
events through the port — it owns no world state. The same fold callable
could be placed on the consumer side by a different profile; only the
wire payload would change, not this logic.

Two phases, deliberately separated:
  - construction (once): hold the compiled graph, the seed-hydrated
    CellStateManager, and the WorldStateWriter seam.
  - run_trigger (per trigger): fold events → derive readings → persist
    the change ("end the event flow", stubbed) → invoke the graph.
"""

from __future__ import annotations

import logging

from agents.supervisor.state import SupervisorGraph
from runtime.contract import TriggerRequest, TriggerResult
from runtime.orchestrator import invoke_supervisor_for_trigger
from stores.world_state import LoggingWorldStateWriter, WorldStateWriter
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
        world_state_writer: WorldStateWriter | None = None,
    ) -> None:
        self._graph = supervisor_graph
        self._manager = cell_state_manager
        self._writer: WorldStateWriter = world_state_writer or LoggingWorldStateWriter()

    async def run_trigger(self, request: TriggerRequest) -> TriggerResult:
        """Fold the trigger's events onto the seed-hydrated world and run
        the graph.

        Returns an empty result (no graph invocation) when the folded
        events trip no cell with readings — the same short-circuit the
        streaming loop applied when its coalesced payload was empty.
        """
        # ── Fold events onto the immutable-seed world (the "shim") ──────
        triggered: set[tuple[int, int]] = set()
        for event in request.events:
            for _cluster_id, row, col in self._manager.update(event):
                triggered.add((row, col))

        payload = self._manager.readings_for(positions=triggered)

        included: set[tuple[int, int]] = set()
        for readings in payload.values():
            for r in readings:
                included.add((r.position.row, r.position.col))
        self._manager.mark_cells_evaluated(included)

        # ── End the event flow: persist the change (stubbed; seed is
        #    immutable). CQRS ordering: write before the graph runs. ─────
        self._writer.write(
            correlation_id=request.correlation_id,
            changed_cells=triggered,
        )

        if not payload:
            logger.info(
                "Trigger %s: %d event(s) folded, no triggered readings — graph not invoked",
                request.correlation_id,
                len(request.events),
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
