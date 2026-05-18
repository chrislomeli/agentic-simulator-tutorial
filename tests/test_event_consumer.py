"""Tests for EventConsumer — the extracted consumer-role loop.

EventConsumer is what a split deployment runs alone and what
RuntimeOrchestrator composes for the collapsed profile. These assert the
loop's contract: drain a tick, forward the events as one TriggerRequest
through the GraphClient port, fold the result into stats — owning no
world state (it does not fold).
"""

from __future__ import annotations

import asyncio

from agents.supervisor.state import RiskScore
from runtime.contract import TriggerRequest, TriggerResult
from runtime.orchestrator import EventConsumer
from world.transport import SensorEvent, SensorEventQueue


def _event(source_id: str) -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id,
        source_type="temperature",
        cluster_id="c1",
        payload={"celsius": 40.0},
    )


class FakeGraphClient:
    """Records every TriggerRequest the consumer forwards."""

    def __init__(self):
        self.requests: list[TriggerRequest] = []

    async def invoke(self, request: TriggerRequest) -> TriggerResult:
        self.requests.append(request)
        return TriggerResult(
            correlation_id=request.correlation_id,
            cluster_ids=["c1"],
            cluster_score={"c1": RiskScore(risk_score=5, confidence=4)},
            assessments_produced=2,
        )


async def test_consumer_coalesces_tick_into_one_trigger():
    queue = SensorEventQueue()
    await queue.put(_event("a"))
    await queue.put(_event("b"))
    await queue.put(_event("c"))

    client = FakeGraphClient()
    consumer = EventConsumer(queue=queue, graph_client=client)

    # drain_until: stop once the queue is empty (mimics "producer done").
    stats = await asyncio.wait_for(
        consumer.run(drain_until=lambda: queue.empty()),
        timeout=2.0,
    )

    # All three events landed in a single trigger (one per tick).
    assert len(client.requests) == 1
    assert [e.source_id for e in client.requests[0].events] == ["a", "b", "c"]
    assert stats.events_consumed == 3
    assert stats.graph_invocations == 1
    assert stats.risk_assessments_produced == 2
    assert stats.cluster_score["c1"] == RiskScore(risk_score=5, confidence=4)


async def test_consumer_stop_is_cooperative():
    queue = SensorEventQueue()
    client = FakeGraphClient()
    consumer = EventConsumer(queue=queue, graph_client=client)

    task = asyncio.create_task(consumer.run())  # no drain_until → runs until stop
    await asyncio.sleep(0.05)
    consumer.stop()
    stats = await asyncio.wait_for(task, timeout=2.0)

    assert stats.graph_invocations == 0  # nothing was ever queued
    assert client.requests == []
