"""
runtime.orchestrator

The collapsed-profile runtime loop: it owns the producer half and is a
*thin consumer bridge* — it forwards events through the GraphClient
port. It deliberately holds no world state.

Architecture
────────────
    SensorPublisher ──► EventQueue ──► RuntimeOrchestrator
        │                                       │
        │ (drives engine.tick() per cycle)      │ batch one tick of events
        ▼                                       ▼
    GenericWorldEngine               GraphClient.invoke(TriggerRequest(events))
                                                │
                                                ▼
                                   GraphFacade (behind the port)
                                   folds events onto the immutable
                                   seed, then runs the supervisor graph

The fold (CellStateManager) lives on the graph side now (see
``runtime.facade``). The consumer detects nothing and folds nothing —
moving that work past the port is what lets the same code run collapsed
in one process or split across containers, chosen by the profile.

The orchestrator owns:

  1. A SensorPublisher — produces SensorEvents on a tick cadence and
     puts them on the EventQueue. Drives engine.tick() per cycle.
  2. A GraphClient port — one TriggerRequest per tick. The adapter
     (in-process / HTTP / AgentCore) is bound by the deployment profile.

What the orchestrator is NOT
────────────────────────────
  * Not a LangGraph node — it sits outside the graph hierarchy.
  * Not responsible for physics. The engine ticks via the publisher.
  * Not a world-state owner — the facade behind the port folds state
    onto the seed; the consumer is a transport bridge only.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents.commons.schemas import CellReadings
from agents.supervisor.state import RiskScore, SupervisorGraph, SupervisorState
from runtime.contract import GraphClient, TriggerRequest
from world.generic_engine import GenericWorldEngine
from world.sensor_inventory import SensorInventory
from world.sensors import SensorPublisher
from world.transport import EventQueue, SensorEvent, SensorEventQueue

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


# ── Trigger → graph invocation seam ──────────────────────────────────────────


@dataclass
class SupervisorInvocation:
    """Structured outcome of one supervisor graph invocation.

    Deliberately carries no RuntimeStats / orchestrator state — it is what
    a single trigger produced, nothing about how the loop accumulates it.
    """

    cluster_ids: list[str]
    cluster_score: dict[str, RiskScore]
    assessments_produced: int


async def invoke_supervisor_for_trigger(
    supervisor_graph: SupervisorGraph,
    payload: dict[str, list[CellReadings]],
) -> SupervisorInvocation:
    """Invoke the supervisor graph for one trigger's worth of clusters.

    Pure with respect to runtime state: it does not touch the publisher,
    the queue, the asyncio loop, or RuntimeStats. The local loop folds the
    returned summary into its stats; a stateless entrypoint (e.g. a Bedrock
    AgentCore handler) can call this directly with a trigger payload and get
    the same structured outcome. This is the transport/invocation seam — the
    one place a trigger becomes a graph run.
    """
    initial_state = SupervisorState(clusters=payload)
    result = await supervisor_graph.ainvoke(initial_state)

    scores: dict[str, RiskScore] = result.get("cluster_score") or {}
    findings: dict = result.get("cluster_findings") or {}
    total = sum(len(v) for v in findings.values())

    logger.info(
        "Supervisor graph complete: %d cluster(s), scores=%s, %d assessment(s)",
        len(payload),
        scores,
        total,
    )
    return SupervisorInvocation(
        cluster_ids=list(payload),
        cluster_score=scores,
        assessments_produced=total,
    )


# ── Event consumer (the thin bridge) ─────────────────────────────────────────


class EventConsumer:
    """Reads events off the EventQueue and forwards them through the
    GraphClient port. Owns no world state — the facade behind the port
    folds onto the immutable seed.

    This is the consumer *role*, separable from the producer so the
    deployment profile can collapse them into one process
    (RuntimeOrchestrator) or split them across containers. The loop is
    identical either way; only ``drain_until`` differs — a collapsed run
    stops when its local producer is done, a standalone consumer runs
    until ``stop()``.
    """

    def __init__(
        self,
        *,
        queue: EventQueue,
        graph_client: GraphClient,
    ) -> None:
        self._queue = queue
        self._graph_client = graph_client
        self._stats = RuntimeStats()
        self._stop_requested = False

    @property
    def stats(self) -> RuntimeStats:
        """Snapshot of stats accumulated by the current/last run()."""
        return self._stats

    def stop(self) -> None:
        """Cooperative stop — checked at the top of each loop iteration."""
        self._stop_requested = True

    async def run(
        self,
        *,
        drain_until: Callable[[], bool] | None = None,
    ) -> RuntimeStats:
        """Consume until ``stop()`` or, when given, ``drain_until()`` is
        true on an idle tick (producer finished and queue drained).

        ``drain_until`` is how the collapsed orchestrator signals "the
        local producer is done"; a standalone consumer container passes
        nothing and runs until stopped.
        """
        self._stop_requested = False
        self._stats = RuntimeStats()

        while True:
            if self._stop_requested:
                break

            # Wait for the next event with a short timeout — the heartbeat
            # that lets us notice the producer finishing without busy-looping.
            try:
                first_event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=_QUEUE_POLL_INTERVAL_SEC,
                )
            except TimeoutError:
                if drain_until is not None and drain_until():
                    break
                continue

            # Drain everything else already queued. Events from the same
            # producer tick land back-to-back, so this batch is one logical
            # "moment" of the world. Coalescing here means one trigger per
            # tick no matter how many cells tripped.
            #
            # TRADE-OFF: this implicitly tick-aligns by relying on producer
            # cadence. If the producer ever emits continuously with no idle
            # gap, this drain would never settle. Today it sleeps between
            # ticks, so there is a natural gap we exploit.
            tick_events = [first_event]
            while True:
                try:
                    tick_events.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Thin bridge: count, ack, forward. No world-state fold here —
            # that is the facade's job, behind the port.
            for _event in tick_events:
                self._stats.events_consumed += 1
                self._queue.task_done()

            if tick_events:
                await self._dispatch_trigger(tick_events)

        return self._stats

    async def _dispatch_trigger(self, events: list[SensorEvent]) -> None:
        """Forward one tick's events as a TriggerRequest through the
        GraphClient port and fold the TriggerResult into RuntimeStats.

        Whether the port is an in-process call or a network hop is a
        profile decision this loop is blind to. ``graph_invocations``
        counts trigger dispatches (one per tick with ≥1 event); the
        facade may still short-circuit if no folded cell has readings.
        """
        request = TriggerRequest(
            correlation_id=str(uuid.uuid4()),
            events=events,
        )
        result = await self._graph_client.invoke(request)

        self._stats.graph_invocations += 1
        for cluster_id in result.cluster_ids:
            self._stats.invocations_by_cluster[cluster_id] = (
                self._stats.invocations_by_cluster.get(cluster_id, 0) + 1
            )

        # Accumulate per-cluster risk scores across ticks (latest per cluster).
        for cluster_id, score in result.cluster_score.items():
            self._stats.cluster_score[cluster_id] = score

        self._stats.risk_assessments_produced += result.assessments_produced


# ── Orchestrator (collapsed: producer + consumer in one process) ─────────────


class RuntimeOrchestrator:
    """
    Composes the producer (SensorPublisher) and the consumer
    (EventConsumer) into a single async run loop — the collapsed /
    single-executable binding of the two roles.

    Lifecycle
    ─────────
        orch = RuntimeOrchestrator(
            sensor_inventory=inv,
            engine=engine,
            graph_client=client,
        )
        stats = await orch.run(ticks=20)

    The orchestrator does NOT instantiate the graph or pick a transport —
    it depends only on the ``GraphClient`` Protocol. The composition root
    (the deployment profile) binds the adapter: in-process for the
    collapsed profile, an HTTP/AgentCore hop when the graph is its own
    deployable. The streaming path and ``main`` now share this one seam.
    """

    def __init__(
        self,
        *,
        sensor_inventory: SensorInventory,
        engine: GenericWorldEngine,
        graph_client: GraphClient,
        sampler: SamplerFn | None = None,
        tick_interval_seconds: float = 1.0,
        queue_max_size: int = 1000,
        event_queue: EventQueue | None = None,
        location_count: int | None = None,
    ) -> None:
        """
        Parameters
        ──────────
        sensor_inventory  : registered sensors, source of truth for
                            placement and cluster membership.
        engine            : the loaded world; ticked once per publisher
                            cycle so sensors read fresh state.
        graph_client      : the GraphClient port. The consumer emits a
                            TriggerRequest through it and is blind to
                            whether the graph is in-process or a remote
                            deployable — the profile binds the adapter.
        sampler           : (engine, row, col) -> local_conditions dict.
                            Defaults to default_sampler.
        tick_interval_seconds : how fast the publisher cycles. Set low
                                (e.g. 0.05) for fast smoke tests.
        queue_max_size    : back-pressure threshold for the default
                            in-process queue. Ignored if event_queue is
                            injected.
        event_queue       : the EventQueue adapter (transport seam). None
                            (default) builds the in-process SensorEventQueue
                            — the local single-process binding. The
                            deployment profile injects a broker adapter
                            here for split producer/consumer containers;
                            this class's loop does not change either way.
        location_count    : sensors to sample per tick. None = all sensors
                            (default). Pass an int to throttle LLM cost.
        """
        self._inventory = sensor_inventory
        self._engine = engine
        self._sampler = sampler or default_sampler

        self._queue: EventQueue = event_queue or SensorEventQueue(maxsize=queue_max_size)
        self._publisher = SensorPublisher(
            inventory=sensor_inventory,
            queue=self._queue,
            tick_interval_seconds=tick_interval_seconds,
            engine=engine,
            sampler=self._sampler,
        )
        # The consumer role, same class a split deployment runs alone.
        self._consumer = EventConsumer(
            queue=self._queue,
            graph_client=graph_client,
        )

        self._location_count = location_count

    # ── Public API ──────────────────────────────────────────────────────────

    async def run(self, *, ticks: int | None = None) -> RuntimeStats:
        """Drive the collapsed loop until ``ticks`` cycles complete or
        ``stop()`` is called.

        This is purely the *collapse*: the producer (SensorPublisher) runs
        as a background task and the consumer (EventConsumer) runs in the
        foreground, both in this one process — the local / single-
        executable binding. A split profile runs the *same* publisher and
        the *same* EventConsumer in separate containers; only the wiring
        differs, never these classes.

        Parameters
        ──────────
        ticks : if provided, stop after the publisher completes this
                many tick cycles. If None, run until stop() is called.

        Returns
        ───────
        RuntimeStats (per-cluster risk scores included).
        """
        publisher_task = asyncio.create_task(
            self._publisher.run(ticks=ticks, location_count=self._location_count),
            name="sensor-publisher",
        )

        try:
            stats = await self._consumer.run(
                drain_until=lambda: publisher_task.done() and self._queue.empty(),
            )
        finally:
            # Make sure the publisher cleans up even if the consumer
            # raised. stop() is cooperative; await ensures the task
            # completes (or its exception surfaces).
            if not publisher_task.done():
                self._publisher.stop()
            await publisher_task

        stats.ticks_completed = self._publisher.ticks_completed
        return stats

    def stop(self) -> None:
        """Cooperative stop — stops both the producer and the consumer."""
        self._publisher.stop()
        self._consumer.stop()

    @property
    def stats(self) -> RuntimeStats:
        """Snapshot of stats accumulated by the current/last run()."""
        return self._consumer.stats
