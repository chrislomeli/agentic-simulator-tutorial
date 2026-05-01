"""
ogar.bridge.consumer

Async event bridge consumer — reads SensorEvents from the queue and
writes aggregated location state into a LocationStateStore.

Responsibility
──────────────
The consumer sits between the transport queue and the location state
store.  Its job is:
  1. Pull SensorEvents from the queue as they arrive.
  2. Map each event's payload fields into a composite location state dict.
  3. Write the updated state to the LocationStateStore.

The store is the seam between the data pipeline and the event loop.
The event loop reads from the store, filters, and invokes the supervisor.
The consumer never touches agents, graphs, or LLMs.

Aggregation model
─────────────────
Multiple sensors contribute to one location's state.  A temperature
sensor updates `temperature_c`, a humidity sensor updates `humidity_pct`,
etc.  The consumer does a read-modify-write on the store so that each
sensor reading merges into the existing composite state.

The grouping key is `cluster_id` — all sensors in a cluster contribute
to one location record.  This matches the supervisor's fan-out: one
cluster agent per cluster_id.

Field mapping
─────────────
The consumer uses a pluggable field_mapper function to translate
SensorEvent payloads into location state fields.  A default mapper
for wildfire sensors is provided (DEFAULT_FIELD_MAPPER).

Usage
─────
  from event_loop.store import InMemoryLocationStore

  store = InMemoryLocationStore()
  consumer = EventBridgeConsumer(queue=queue, store=store)
  con_task = asyncio.create_task(consumer.run())

  # The event loop reads from the same store:
  event_loop = EventLoop(config, store=store, on_batch=invoke_supervisor)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from event_loop.store import LocationStateStore
from transport.queue import SensorEventQueue
from transport.schemas import SensorEvent

logger = logging.getLogger(__name__)


# ── Default field mapper for wildfire sensors ────────────────────────────────

def _wildfire_field_mapper(event: SensorEvent) -> dict[str, Any]:
    """
    Map a wildfire SensorEvent payload into location state fields.

    Each sensor type contributes specific fields to the composite
    location state.  Unknown sensor types are silently ignored —
    they still get stored as raw events but don't update named fields.
    """
    fields: dict[str, Any] = {}
    p = event.payload

    if event.source_type == "temperature":
        fields["temperature_c"] = p.get("celsius", 0.0)
    elif event.source_type == "humidity":
        fields["humidity_pct"] = p.get("relative_humidity_pct", 100.0)
    elif event.source_type == "wind":
        fields["wind_speed_mps"] = p.get("speed_mps", 0.0)
        fields["wind_direction_deg"] = p.get("direction_deg", 0.0)
    elif event.source_type == "smoke":
        fields["smoke_pm25"] = p.get("pm25_ugm3", 0.0)
    elif event.source_type == "barometric_pressure":
        fields["pressure_hpa"] = p.get("pressure_hpa", 1013.0)

    return fields


DEFAULT_FIELD_MAPPER = _wildfire_field_mapper


class EventBridgeConsumer:
    """
    Async consumer that reads SensorEvents and writes composite
    location state into a LocationStateStore.

    Parameters
    ──────────
    queue        : The SensorEventQueue to consume from.
    store        : LocationStateStore to write aggregated state into.
    field_mapper : Callable that maps a SensorEvent → dict of location
                   state fields to merge.  Defaults to the wildfire mapper.
    """

    def __init__(
        self,
        *,
        queue: SensorEventQueue,
        store: LocationStateStore,
        field_mapper: Callable[[SensorEvent], dict[str, Any]] = DEFAULT_FIELD_MAPPER,
    ) -> None:
        self._queue = queue
        self._store = store
        self._field_mapper = field_mapper
        self.events_by_cluster: dict[str, list[SensorEvent]] = {}
        self.events_consumed: int = 0
        self._stop_requested: bool = False

    def stop(self) -> None:
        """Signal the consumer to stop after the current event."""
        logger.info("EventBridgeConsumer stop requested")
        self._stop_requested = True

    async def run(self, max_events: int | None = None) -> None:
        """
        Run the consumer loop.

        Parameters
        ──────────
        max_events : If provided, stop after consuming this many events.
                     If None, run until stop() is called or the task is cancelled.
        """
        self._stop_requested = False
        self.events_consumed = 0
        self.events_by_cluster = {}

        logger.info(
            "EventBridgeConsumer starting — limit=%s",
            max_events if max_events is not None else "∞",
        )

        while True:
            if self._stop_requested:
                logger.info(
                    "EventBridgeConsumer stopped after %d events",
                    self.events_consumed,
                )
                break

            if max_events is not None and self.events_consumed >= max_events:
                logger.info(
                    "EventBridgeConsumer reached event limit (%d)",
                    max_events,
                )
                break

            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue

            self.events_consumed += 1
            cluster_id = event.cluster_id

            logger.debug(
                "Consumed event %s from %s (cluster=%s, tick=%d)",
                event.event_id,
                event.source_id,
                cluster_id,
                event.sim_tick,
            )

            # ── Aggregate into location state store ──────────────────
            self._merge_into_store(event)

            # ── Also keep raw events for backward compat / inspection ─
            if cluster_id not in self.events_by_cluster:
                self.events_by_cluster[cluster_id] = []
            self.events_by_cluster[cluster_id].append(event)

            self._queue.task_done()

    # ── Store aggregation ──────────────────────────────────────────────────────

    def _merge_into_store(self, event: SensorEvent) -> None:
        """
        Read-modify-write: merge a sensor event's fields into the
        composite location state for its cluster.

        If the location has no prior state, a new record is created
        with safe defaults.  The field_mapper decides which fields
        the event contributes.
        """
        location_id = event.cluster_id
        existing = self._store.get(location_id)
        current = dict(existing) if existing else {"location_id": location_id}
        current["location_id"] = location_id

        # Merge sensor-specific fields
        mapped = self._field_mapper(event)
        current.update(mapped)

        # Track the latest tick for freshness
        current["sim_tick"] = event.sim_tick
        current["timestamp"] = event.timestamp.isoformat()

        self._store.set(location_id, current)

    # ── Batch interface (backward compat) ────────────────────────────────────

    def drain_batch(self) -> dict[str, list[SensorEvent]]:
        """
        Pull the current batch of raw events and reset the buffer.

        This is the legacy interface for code that works with raw
        SensorEvents directly (e.g. supervisor_runner.py).  New code
        should read from the LocationStateStore instead.

        Returns
        ───────
        dict mapping cluster_id → list of SensorEvents accumulated since
        the last drain.  The internal buffer is cleared after this call.
        """
        batch = self.events_by_cluster
        self.events_by_cluster = {}
        drained = self.events_consumed
        self.events_consumed = 0
        logger.info(
            "EventBridgeConsumer drained %d events across %d cluster(s)",
            drained, len(batch),
        )
        return batch
