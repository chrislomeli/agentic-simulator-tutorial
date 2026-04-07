"""
ogar.sensors.publisher

Async sensor publisher loop.

Responsibility
──────────────
The publisher sits between sensors and the transport layer.
Its only job is:
  1. Call emit() on each registered sensor at regular tick intervals.
  2. Put the resulting SensorEvent onto the event queue.
  3. Skip None returns (dropout mode) silently.

The publisher does NOT know about Kafka, LangGraph, or agents.
It only knows about sensors and the event queue interface.

Why async?
──────────
In a real system sensors would be I/O-bound (reading from hardware,
network sockets, or a simulation engine).  async lets multiple sensors
tick concurrently without blocking each other.

In this mock setup the sensors are purely CPU-bound (random number
generation), but the async structure is already correct for when we
swap in a real world engine or Kafka producer.

Tick interval
─────────────
The tick_interval_seconds parameter controls how fast the simulation
runs.  Set it low (0.1s) for fast scenario testing.  Set it to match
wall-clock time (1.0s) for realistic demos.

Usage
─────
  queue = SensorEventQueue()
  publisher = SensorPublisher(sensors=[temp_sensor, smoke_sensor], queue=queue)
  await publisher.run()        # runs forever until cancelled
  # or:
  await publisher.run(ticks=50)  # runs for exactly 50 ticks then stops
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List, Optional

from sensors.base import SensorBase
from transport.queue import SensorEventQueue

if TYPE_CHECKING:
    from world.generic_engine import GenericWorldEngine
    from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)


class SensorPublisher:
    """
    Async loop that ticks all registered sensors and enqueues their events.

    Each call to run() ticks all sensors in sequence, waits for
    tick_interval_seconds, then repeats.  Sensors are ticked in
    registration order — not in parallel — to keep the tick counter
    consistent across sensors.

    If a sensor is in DROPOUT mode, emit() returns None.  The publisher
    simply skips it and moves on — no error, no log noise.
    """

    def __init__(
        self,
        *,
        sensors: Optional[List[SensorBase]] = None,
        inventory: Optional["SensorInventory"] = None,
        queue: SensorEventQueue,
        tick_interval_seconds: float = 1.0,
        engine: Optional["GenericWorldEngine"] = None,
    ) -> None:
        """
        Parameters
        ──────────
        sensors               : List of sensors to tick each interval.
                                All must be SensorBase subclasses.
                                Ignored when inventory is provided.
        inventory             : Optional SensorInventory.  When provided,
                                the publisher iterates inventory.all_sensors()
                                each tick — this is live, so thinning or adding
                                sensors between ticks takes effect immediately.
        queue                 : The event queue to put events onto.
                                The bridge consumer reads from the other end.
        tick_interval_seconds : How long to wait between tick cycles.
                                Default 1.0s = one tick per second.
                                Set lower for faster scenario replay.
        engine                : Optional GenericWorldEngine.  When provided
                                the publisher calls engine.tick() once before
                                each sensor pass, advancing the simulation
                                so sensors read fresh world state.
        """
        if inventory is None and sensors is None:
            raise ValueError("Provide either sensors or inventory")
        self._sensors = sensors
        self._inventory = inventory
        self._queue = queue
        self._tick_interval = tick_interval_seconds
        self._engine = engine

        # Total ticks completed since run() was last called.
        # Useful for scenario scripts that want to know how far we are.
        self.ticks_completed: int = 0

        # Set to True by stop() to break the run loop cleanly.
        self._stop_requested: bool = False

    def stop(self) -> None:
        """
        Signal the run loop to stop after completing the current tick.

        This is a cooperative stop — the loop checks this flag at the
        start of each iteration.  It does not interrupt a tick in progress.
        """
        logger.info("SensorPublisher stop requested")
        self._stop_requested = True

    async def run(self, ticks: Optional[int] = None) -> None:
        """
        Run the publisher loop.

        Parameters
        ──────────
        ticks : If provided, stop after this many tick cycles.
                If None, run forever until stop() is called or the
                task is cancelled.

        This coroutine is meant to be run as an asyncio Task:
          task = asyncio.create_task(publisher.run())
          ...
          task.cancel()
        """
        self._stop_requested = False
        self.ticks_completed = 0

        sensor_count = (
            self._inventory.size if self._inventory is not None
            else len(self._sensors)
        )
        logger.info(
            "SensorPublisher starting — %d sensor(s), %.2fs interval, limit=%s",
            sensor_count,
            self._tick_interval,
            ticks if ticks is not None else "∞",
        )

        while True:
            # ── Check stop conditions ───────────────────────────────────
            if self._stop_requested:
                logger.info("SensorPublisher stopped by request after %d ticks", self.ticks_completed)
                break

            if ticks is not None and self.ticks_completed >= ticks:
                logger.info("SensorPublisher reached tick limit (%d)", ticks)
                break

            # ── Advance the world simulation (if wired) ───────────────
            if self._engine is not None:
                self._engine.tick()
                logger.debug(
                    "WorldEngine ticked to %d",
                    self._engine.current_tick,
                )

            # ── Tick all sensors ────────────────────────────────────────
            active_sensors = (
                self._inventory.all_sensors()
                if self._inventory is not None
                else self._sensors
            )
            for sensor in active_sensors:
                event = sensor.emit()

                if event is None:
                    # Sensor is in DROPOUT mode — silence is intentional,
                    # log at debug only to avoid noise in the demo output.
                    logger.debug(
                        "Sensor %s emitted None (DROPOUT) at tick %d",
                        sensor.source_id,
                        self.ticks_completed,
                    )
                    continue

                # Put the event on the queue.
                # put() blocks if the queue is full — this provides natural
                # back-pressure: if the bridge consumer is slow, the publisher
                # will slow down rather than filling memory.
                await self._queue.put(event)

                logger.debug(
                    "Published event from %s (tick=%d, cluster=%s)",
                    event.source_id,
                    event.sim_tick,
                    event.cluster_id,
                )

            self.ticks_completed += 1

            # ── Wait for next tick ──────────────────────────────────────
            await asyncio.sleep(self._tick_interval)
