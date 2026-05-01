"""
ogar.transport.queue

In-process async event queue — the pre-Kafka transport layer.

Why this exists
───────────────
Before we wire in Kafka, we need something that:
  - Decouples the sensor publisher from the bridge consumer.
  - Provides back-pressure (publisher blocks if consumer is slow).
  - Is easy to swap out for a real Kafka consumer later.

This module wraps asyncio.Queue with a typed interface that matches
the shape we'll eventually want from a Kafka consumer wrapper.
When we add Kafka, the bridge consumer can switch from reading
SensorEventQueue to reading a KafkaConsumerWrapper — the bridge
code itself does not change.

Kafka comparison
────────────────
asyncio.Queue is single-process only.  Kafka is distributed.
For the demo this doesn't matter — everything runs in one process.
The architecture already separates concerns correctly:
  sensors → queue → bridge consumer → workflow runner
The "queue" is the only thing that changes when Kafka arrives.

Back-pressure
─────────────
The queue has a configurable max size.  When full, put() blocks
the publisher coroutine.  This is intentional — it means the
system slows down rather than accumulating unbounded memory when
agents can't keep up.  In production Kafka would handle this via
consumer lag monitoring.

Usage
─────
  queue = SensorEventQueue(maxsize=100)
  await queue.put(event)                  # publisher side
  event = await queue.get()              # consumer side
  queue.task_done()                      # mark event processed
"""

from __future__ import annotations

import asyncio
import logging

from transport.schemas import SensorEvent

logger = logging.getLogger(__name__)


class SensorEventQueue:
    """
    Typed async FIFO queue for SensorEvent objects.

    Thin wrapper around asyncio.Queue[SensorEvent].
    The type annotation prevents accidentally putting non-SensorEvent
    objects on the queue, which would cause confusing errors downstream.
    """

    def __init__(self, maxsize: int = 0) -> None:
        """
        Parameters
        ──────────
        maxsize : Maximum number of events to hold before put() blocks.
                  0 means unbounded (no back-pressure).
                  Default 0 — suitable for demos where timing doesn't matter.
                  Set to a real value (e.g. 1000) when simulating load.
        """
        # asyncio.Queue[SensorEvent] is the underlying implementation.
        # We expose only the methods we need so the interface is minimal
        # and easy to replicate in a future Kafka wrapper.
        self._queue: asyncio.Queue[SensorEvent] = asyncio.Queue(maxsize=maxsize)

        # Running count of events put onto the queue since creation.
        # Useful for logging and assertions in tests.
        self.total_enqueued: int = 0

    async def put(self, event: SensorEvent) -> None:
        """
        Put an event on the queue.

        Blocks if the queue is full (back-pressure).
        The publisher calls this after every non-None emit().
        """
        await self._queue.put(event)
        self.total_enqueued += 1
        logger.debug(
            "Queue: enqueued event_id=%s (qsize=%d, total=%d)",
            event.event_id,
            self._queue.qsize(),
            self.total_enqueued,
        )

    async def get(self) -> SensorEvent:
        """
        Get the next event from the queue.

        Blocks if the queue is empty.
        The bridge consumer calls this in its read loop.
        """
        event = await self._queue.get()
        logger.debug(
            "Queue: dequeued event_id=%s (qsize=%d)",
            event.event_id,
            self._queue.qsize(),
        )
        return event

    def task_done(self) -> None:
        """
        Mark the most recently dequeued event as fully processed.

        Call this after the bridge consumer has successfully handed
        the event to the workflow runner.  Mirrors asyncio.Queue.task_done()
        and will mirror Kafka's manual offset commit when we switch.
        """
        self._queue.task_done()

    def qsize(self) -> int:
        """Return the current number of events waiting in the queue."""
        return self._queue.qsize()

    def empty(self) -> bool:
        """Return True if the queue has no events waiting."""
        return self._queue.empty()

    async def join(self) -> None:
        """
        Block until all enqueued items have been processed.

        Useful in tests: enqueue N events, then await queue.join()
        to confirm all were consumed before asserting results.
        """
        await self._queue.join()
