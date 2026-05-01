"""
ogar.bridge.pipeline_runner

Manages the pub/sub pipeline lifecycle: publisher + consumer running as
concurrent async tasks, with a drain_batch() interface for the orchestrator.

Design intent
─────────────
In production, the publisher (world engine side) and consumer (agent side)
would be separate processes connected by Kafka.  This class co-locates them
in a single process for development and testing, but preserves the same
interface that a Kafka-backed consumer would expose:

    runner.drain_batch() → dict[str, list[SensorEvent]]

When you swap to Kafka, you replace the internals (asyncio.Queue → Kafka
topic, EventBridgeConsumer → KafkaConsumer) but the drain_batch() signature
stays the same.  The orchestrator and supervisor never know the difference.

Usage
─────
  runner = PipelineRunner(engine, sensor_inventory, sampler=sample_local_conditions)
  await runner.start(tick_interval=0.0)

  # Orchestrator loop:
  while runner.is_running:
      await asyncio.sleep(1.0)
      batch = runner.drain_batch()
      if batch:
          supervisor_graph.invoke({"events_by_cluster": batch, ...})

  await runner.stop()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from bridge.consumer import EventBridgeConsumer
from event_loop.store import InMemoryLocationStore, LocationStateStore
from sensors.publisher import SensorPublisher
from transport.queue import SensorEventQueue
from transport.schemas import SensorEvent

if TYPE_CHECKING:
    from world.generic_engine import GenericWorldEngine
    from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)

# Type alias matching SensorPublisher's sampler signature
SamplerFn = Callable[..., dict[str, Any]]


class PipelineRunner:
    """
    Manages the concurrent pub/sub pipeline.

    Encapsulates:
      - SensorEventQueue (the in-memory transport)
      - SensorPublisher (produces sensor events from the world engine)
      - EventBridgeConsumer (aggregates events into LocationStateStore)

    Exposes:
      - start() / stop() — async lifecycle management
      - drain_batch() — pull raw accumulated events (backward compat)
      - store — the LocationStateStore the consumer writes into
      - ticks_completed — how many world ticks the publisher has processed
      - is_running — whether the pipeline tasks are active
    """

    def __init__(
        self,
        engine: GenericWorldEngine,
        sensor_inventory: SensorInventory,
        *,
        sampler: SamplerFn,
        store: LocationStateStore | None = None,
        queue_maxsize: int = 500,
    ) -> None:
        self._engine = engine
        self._sensor_inventory = sensor_inventory
        self._sampler = sampler
        self._store = store or InMemoryLocationStore()
        self._queue_maxsize = queue_maxsize

        # Built during start()
        self._queue: SensorEventQueue | None = None
        self._publisher: SensorPublisher | None = None
        self._consumer: EventBridgeConsumer | None = None
        self._pub_task: asyncio.Task | None = None
        self._con_task: asyncio.Task | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        num_ticks: int | None = None,
        tick_interval: float = 0.0,
    ) -> None:
        """
        Build the queue, publisher, and consumer, then launch them as
        concurrent async tasks.

        Parameters
        ──────────
        num_ticks      : Total ticks to run.  None = run until stop().
        tick_interval  : Seconds between publisher ticks.  0.0 = fast as possible.
        """
        if self._pub_task is not None:
            raise RuntimeError("Pipeline is already running")

        self._queue = SensorEventQueue(maxsize=self._queue_maxsize)

        self._publisher = SensorPublisher(
            inventory=self._sensor_inventory,
            queue=self._queue,
            tick_interval_seconds=tick_interval,
            engine=self._engine,
            sampler=self._sampler,
        )

        self._consumer = EventBridgeConsumer(queue=self._queue, store=self._store)

        self._pub_task = asyncio.create_task(
            self._publisher.run(ticks=num_ticks),
            name="pipeline-publisher",
        )
        self._con_task = asyncio.create_task(
            self._consumer.run(),
            name="pipeline-consumer",
        )

        logger.info(
            "PipelineRunner started — ticks=%s, interval=%.2fs",
            num_ticks if num_ticks is not None else "∞",
            tick_interval,
        )

    async def stop(self) -> None:
        """
        Shut down the pipeline cleanly.

        Waits for the publisher to finish (if tick-limited), then signals
        the consumer to stop, and awaits both tasks.
        """
        if self._pub_task is None:
            return

        # Wait for publisher to complete (it will if num_ticks was set)
        if not self._pub_task.done():
            await self._pub_task

        # Signal consumer to stop and wait for it to drain
        if self._consumer is not None:
            self._consumer.stop()
        if self._con_task is not None:
            await self._con_task

        logger.info(
            "PipelineRunner stopped — %d ticks completed",
            self.ticks_completed,
        )

        self._pub_task = None
        self._con_task = None

    async def run_to_completion(
        self,
        *,
        num_ticks: int,
        tick_interval: float = 0.0,
    ) -> dict[str, list[SensorEvent]]:
        """
        Run the full pipeline and return all collected events.

        Convenience method for standalone use (no supervisor needed).
        Starts the pipeline, waits for all ticks, drains everything,
        and shuts down cleanly.

        Returns
        ───────
        dict mapping cluster_id → list of SensorEvents collected
        across all ticks.
        """
        await self.start(num_ticks=num_ticks, tick_interval=tick_interval)
        await self.stop()
        return self.drain_batch()

    # ── Batch interface (what the orchestrator calls) ──────────────────────────

    def drain_batch(self) -> dict[str, list[SensorEvent]]:
        """
        Pull accumulated events grouped by cluster and reset the buffer.

        This is the interface between the pipeline and the supervisor.
        Same signature whether backed by asyncio.Queue or Kafka.

        Returns an empty dict if nothing has accumulated or pipeline
        hasn't started yet.
        """
        if self._consumer is None:
            return {}
        return self._consumer.drain_batch()

    # ── Store access ─────────────────────────────────────────────────────────

    @property
    def store(self) -> LocationStateStore:
        """The LocationStateStore the consumer writes into."""
        return self._store

    # ── Observability ──────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """True if the publisher task is still active."""
        return self._pub_task is not None and not self._pub_task.done()

    @property
    def ticks_completed(self) -> int:
        """Number of world ticks the publisher has completed."""
        if self._publisher is None:
            return 0
        return self._publisher.ticks_completed
