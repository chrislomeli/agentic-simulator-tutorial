"""world.transport.port — the transport-agnostic queue seam.

Why this exists
───────────────
``SensorEventQueue`` (queue.py) is an in-process ``asyncio.Queue`` wrapper.
That is the correct *local* binding, but the producer and the consumer must
not depend on it directly — in the k8s/aws profiles they run in separate
containers and the queue becomes a real broker (Kafka/SQS/Redis), which an
asyncio queue cannot span.

So the producer (``SensorPublisher``) and the consumer
(``RuntimeOrchestrator``) depend only on this ``EventQueue`` Protocol. The
deployment profile injects the adapter:

  - in-process  : ``SensorEventQueue``      (queue.py — laptop / single binary)
  - networked   : ``BrokerEventQueue``      (broker.py — stub until the broker step)

This mirrors the ``runtime.GraphClient`` port exactly: one Protocol, the
collocated adapter is just the trivially-reliable implementation, and
"collapsing into one process" means the profile picks the in-process
adapter — it never means calling the concrete class directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from world.transport.schemas import SensorEvent


@runtime_checkable
class EventQueue(Protocol):
    """Transport-agnostic event queue: producer puts, consumer gets.

    The method set is exactly what the producer/consumer use today, shaped
    so a Kafka/SQS wrapper can satisfy it without either side changing:
    ``get``/``put`` are async (a network hop in the broker case);
    ``task_done`` maps to a manual offset commit; ``join`` is test-only
    drain support.
    """

    async def put(self, event: SensorEvent) -> None: ...

    async def get(self) -> SensorEvent: ...

    def get_nowait(self) -> SensorEvent: ...

    def task_done(self) -> None: ...

    def qsize(self) -> int: ...

    def empty(self) -> bool: ...

    async def join(self) -> None: ...
