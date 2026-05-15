"""
runtime.orchestrator

The runtime loop that drives sensor events from the publisher into the
supervisor graph.

Architecture
────────────
    SensorPublisher ──► SensorEventQueue ──► RuntimeOrchestrator
        │                                            │
        │ (drives engine.tick() per cycle)           │
        ▼                                            ▼
    GenericWorldEngine                       CellStateManager.update()
                                                     │
                                                     │ triggered (cluster_id, row, col)
                                                     ▼
                                    CellStateManager.readings_for(positions)
                                                     │
                                                     │ dict[cluster_id, list[CellReadings]]
                                                     ▼
                                          SupervisorGraph.ainvoke()
                                          (fans out to cluster agents,
                                           aggregates cluster_score +
                                           cluster_findings)

The orchestrator owns three things and one loop:

  1. A SensorPublisher — produces SensorEvents on a tick cadence and
     puts them on an asyncio queue. Drives engine.tick() per cycle.
  2. A CellStateManager — receives every event, maintains per-cell
     state (latest values + recent history), reports triggered
     positions when thresholds cross.
  3. A compiled SupervisorGraph — invoked with pre-populated
     ``clusters`` (CellReadings grouped by cluster_id). The supervisor
     fans out to cluster agents internally via the Send API.

What the orchestrator is NOT
────────────────────────────
  * Not a LangGraph node — it sits outside the graph hierarchy.
  * Not responsible for physics. The engine ticks via the publisher;
    the orchestrator only listens to sensor output.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents.commons.schemas import CellReadings
from agents.supervisor.state import RiskScore, SupervisorGraph, SupervisorState
from world.cell_state_manager import CellStateManager, EvaluationThresholds
from world.generic_engine import GenericWorldEngine
from world.sensor_inventory import SensorInventory
from world.sensors import SensorPublisher
from world.transport import SensorEventQueue

# Idle sleep when waiting on the queue. Short enough that we notice the
# publisher finishing within ~one heartbeat, long enough not to busy-loop.
_QUEUE_POLL_INTERVAL_SEC = 0.1

logger = logging.getLogger(__name__)


# ── Stats record ─────────────────────────────────────────────────────────────


@dataclass
class RuntimeStats:
    """End-of-run summary. Useful for smoke tests and demo scripts."""

    ticks_completed: int = 0
    events_consumed: int = 0
    records_emitted: int = 0
    graph_invocations: int = 0
    invocations_by_cluster: dict[str, int] = field(default_factory=dict)
    risk_assessments_produced: int = 0
    cluster_score: dict[str, RiskScore] = field(default_factory=dict)


# ── Sampler protocol ─────────────────────────────────────────────────────────


SamplerFn = Callable[[GenericWorldEngine, int, int], dict[str, Any]]


def default_sampler(
    engine: GenericWorldEngine,
    grid_row: int,
    grid_col: int,
) -> dict[str, Any]:
    """
    Default ``local_conditions`` builder.

    Reads directly from the cell's per-cell ground truth state. Weather
    is now stored per-cell on FireCellState and evolved by physics each
    tick, so this sampler is just a thin accessor.

    Sensors pick out the keys they care about (temperature reads
    ``ambient_temperature_c``, wind reads ``wind_speed_mps``, etc.)
    and add noise.
    """
    cell = engine.grid.get_cell(grid_row, grid_col)
    return cell.cell_state.to_local_conditions()


# ── Orchestrator ─────────────────────────────────────────────────────────────


class RuntimeOrchestrator:
    """
    Wires SensorPublisher, CellStateManager, and the supervisor graph
    into a single async run loop.

    Lifecycle
    ─────────
        orch = RuntimeOrchestrator(
            sensor_inventory=inv,
            engine=engine,
            supervisor_graph=graph,
        )
        stats = await orch.run(ticks=20)

    The orchestrator does NOT instantiate the graph — that stays in the
    composition root (``main.py``), which owns LLM/prompt-registry wiring.
    """

    def __init__(
        self,
        *,
        sensor_inventory: SensorInventory,
        engine: GenericWorldEngine,
        supervisor_graph: SupervisorGraph,
        cell_state_manager: CellStateManager | None = None,
        thresholds: EvaluationThresholds | None = None,
        sampler: SamplerFn | None = None,
        tick_interval_seconds: float = 1.0,
        queue_max_size: int = 1000,
        location_count: int | None = None,
    ) -> None:
        """
        Parameters
        ──────────
        sensor_inventory  : registered sensors, source of truth for
                            placement and cluster membership.
        engine            : the loaded world; ticked once per publisher
                            cycle so sensors read fresh state.
        supervisor_graph  : compiled SupervisorGraph. Receives
                            pre-collated CollatedRecords grouped by
                            cluster_id and fans out to cluster agents
                            internally.
        thresholds        : when CellStateManager should emit records.
                            Defaults to EvaluationThresholds().
        sampler           : (engine, row, col) -> local_conditions dict.
                            Defaults to default_sampler.
        tick_interval_seconds : how fast the publisher cycles. Set low
                                (e.g. 0.05) for fast smoke tests.
        queue_max_size    : back-pressure threshold. Publisher blocks
                            on put() when reached.
        location_count    : sensors to sample per tick. None = all sensors
                            (default). Pass an int to throttle LLM cost.
        """
        self._inventory = sensor_inventory
        self._engine = engine
        self._supervisor_graph = supervisor_graph
        self._sampler = sampler or default_sampler

        self._queue = SensorEventQueue(maxsize=queue_max_size)
        self._manager = cell_state_manager or CellStateManager(
            world_grid=engine.grid,
            sensor_inventory=sensor_inventory,
            thresholds=thresholds,
        )
        self._publisher = SensorPublisher(
            inventory=sensor_inventory,
            queue=self._queue,
            tick_interval_seconds=tick_interval_seconds,
            engine=engine,
            sampler=self._sampler,
        )

        self._location_count = location_count

        self._stats = RuntimeStats()
        self._stop_requested = False

    # ── Public API ──────────────────────────────────────────────────────────

    async def run(self, *, ticks: int | None = None) -> RuntimeStats:
        """
        Drive the runtime loop until ``ticks`` cycles complete or
        ``stop()`` is called.

        Lifecycle:
          1. Reset stats and start the SensorPublisher as a background task.
             The publisher drives engine.tick() and pushes SensorEvents
             onto the internal queue.
          2. Consume events from the queue, feed each to CellStateManager.
          3. When the manager emits CollatedRecords, group by cluster and
             invoke the supervisor graph. The supervisor fans out to
             cluster agents in parallel via the Send API.
          4. After the publisher finishes (tick limit reached or stop()),
             drain any remaining queued events before returning.

        Parameters
        ──────────
        ticks : if provided, stop after the publisher completes this
                many tick cycles. If None, run until stop() is called.

        Returns
        ───────
        RuntimeStats summarising what flowed through the loop, including
        per-cluster risk scores (``cluster_score``).
        """
        self._stop_requested = False
        self._stats = RuntimeStats()

        publisher_task = asyncio.create_task(
            self._publisher.run(ticks=ticks, location_count=self._location_count),
            name="sensor-publisher",
        )

        try:
            while True:
                if self._stop_requested:
                    break

                # Wait for the next event with a short timeout. The
                # timeout is the heartbeat that lets us notice the
                # publisher finishing without busy-looping.
                try:
                    first_event = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=_QUEUE_POLL_INTERVAL_SEC,
                    )
                except TimeoutError:
                    if publisher_task.done() and self._queue.empty():
                        break
                    continue

                # Drain everything else already on the queue. Events from
                # the same publisher tick land back-to-back, so this batch
                # represents one logical "moment" of the world. Coalescing
                # here means each cluster receives at most one supervisor
                # invocation per tick, no matter how many of its cells tripped.
                #
                # TRADE-OFF: this implicitly tick-aligns by relying on
                # publisher cadence. If the publisher ever switches to
                # continuous emission with no idle gap, this drain would
                # never settle. Today the publisher sleeps between ticks,
                # so there is a natural gap we exploit.
                tick_events = [first_event]
                while True:
                    try:
                        tick_events.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Track which cells triggered. We re-snapshot from the
                # manager at the end of the tick rather than using values
                # from each trigger moment, so the payload reflects the
                # latest state after all events in this tick have landed.
                triggered_positions: set[tuple[int, int]] = set()
                for event in tick_events:
                    self._stats.events_consumed += 1
                    try:
                        triggered = self._manager.update(event)
                    finally:
                        self._queue.task_done()
                    if triggered:
                        self._stats.records_emitted += len(triggered)
                        for _cluster_id, row, col in triggered:
                            triggered_positions.add((row, col))

                # One supervisor invocation per tick. Sector analysis in
                # logistics will provide the landscape-wide context.
                payload: dict[str, list[CellReadings]] = self._manager.readings_for(
                    positions=triggered_positions,
                )

                included_positions: set[tuple[int, int]] = set()
                for readings in payload.values():
                    for r in readings:
                        included_positions.add((r.position.row, r.position.col))

                self._manager.mark_cells_evaluated(included_positions)
                if payload:
                    await self._invoke_supervisor_graph(payload)

        finally:
            # Make sure the publisher cleans up even if the consumer
            # raised. stop() is cooperative; await ensures the task
            # completes (or its exception surfaces).
            if not publisher_task.done():
                self._publisher.stop()
            await publisher_task

        self._stats.ticks_completed = self._publisher.ticks_completed
        return self._stats

    def stop(self) -> None:
        """Cooperative stop — drain in-flight work, then exit run()."""
        self._stop_requested = True
        self._publisher.stop()

    @property
    def stats(self) -> RuntimeStats:
        """Snapshot of stats accumulated by the current/last run()."""
        return self._stats

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _invoke_supervisor_graph(self, payload: dict[str, list[CellReadings]]) -> None:
        """
        Invoke the supervisor graph for one tick's worth of triggered clusters.

        Builds a SupervisorState with ``clusters`` pre-populated. The
        supervisor fans out to one cluster agent per cluster via the Send API,
        then aggregates results into ``cluster_score`` and ``cluster_findings``
        before the assess/decide/dispatch nodes run.
        """
        initial_state = SupervisorState(
            clusters=payload,
        )

        result = await self._supervisor_graph.ainvoke(initial_state)

        self._stats.graph_invocations += 1
        for cluster_id in payload:
            self._stats.invocations_by_cluster[cluster_id] = (
                self._stats.invocations_by_cluster.get(cluster_id, 0) + 1
            )

        # Accumulate per-cluster risk scores across ticks (max per cluster).
        scores: dict[str, RiskScore] = result.get("cluster_score") or {}
        for cluster_id, score in scores.items():
            self._stats.cluster_score[cluster_id] = score

        findings: dict = result.get("cluster_findings") or {}
        total = sum(len(v) for v in findings.values())
        self._stats.risk_assessments_produced += total
        logger.info(
            "Supervisor graph complete: %d cluster(s), scores=%s, %d assessment(s)",
            len(payload),
            scores,
            total,
        )
