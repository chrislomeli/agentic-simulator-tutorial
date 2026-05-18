"""world.transport.broker — networked ``EventQueue`` adapter (stub).

This is the placeholder the k8s-desktop / k8s-deployed / aws profiles wire
in when the producer and consumer run in separate containers and the queue
must cross a process boundary (Kafka, AWS SQS, or Redis Streams).

It is deliberately a *named, shaped stub*, not a hidden gap: it satisfies
the ``EventQueue`` Protocol so the deployment-profile wiring is complete and
type-checks today, but every method raises ``NotImplementedError`` pointing
at the broker step. A reader sees exactly where the real transport belongs
and why it is intentionally absent in this tutorial cut.

Tutorial trade-off (stated, not hidden): only the in-process adapter is
implemented. Swapping a real broker in is a self-contained later step that
touches *only* this file — no producer/consumer code changes, because both
depend on the Protocol, not the implementation.
"""

from __future__ import annotations

from world.transport.schemas import SensorEvent

_NOT_WIRED = (
    "BrokerEventQueue is a stub. The networked broker adapter "
    "(Kafka/SQS/Redis Streams) is wired in the broker step — see "
    "runtime.profiles. Producer/consumer code does not change when it is: "
    "they depend on the world.transport.EventQueue Protocol."
)


class BrokerEventQueue:
    """Networked ``EventQueue`` adapter — Protocol-shaped, not yet implemented.

    Parameters are accepted (broker URL, topic) so profile wiring can
    construct it without special-casing; using it raises until the broker
    step lands a real client here.
    """

    def __init__(self, *, url: str | None = None, topic: str = "sensor-events") -> None:
        self._url = url
        self._topic = topic

    async def put(self, event: SensorEvent) -> None:
        raise NotImplementedError(_NOT_WIRED)

    async def get(self) -> SensorEvent:
        raise NotImplementedError(_NOT_WIRED)

    def get_nowait(self) -> SensorEvent:
        raise NotImplementedError(_NOT_WIRED)

    def task_done(self) -> None:
        raise NotImplementedError(_NOT_WIRED)

    def qsize(self) -> int:
        raise NotImplementedError(_NOT_WIRED)

    def empty(self) -> bool:
        raise NotImplementedError(_NOT_WIRED)

    async def join(self) -> None:
        raise NotImplementedError(_NOT_WIRED)
