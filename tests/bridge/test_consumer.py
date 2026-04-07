"""Tests for ogar.bridge.consumer — EventBridgeConsumer."""

import asyncio

import pytest

from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph
from transport import SensorEventQueue
from transport import SensorEvent


def _make_event(source_id: str = "s1", cluster_id: str = "cluster-north") -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id,
        source_type="temperature",
        cluster_id=cluster_id,
        payload={"celsius": 42.0},
    )


@pytest.fixture
def queue():
    return SensorEventQueue(maxsize=100)


@pytest.fixture
def cluster_graph():
    return build_cluster_agent_graph()


class TestEventBridgeConsumer:
    @pytest.mark.asyncio
    async def test_consume_single_event(self, queue, cluster_graph):
        await queue.put(_make_event())
        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=1,
        )
        await consumer.run(max_events=1)
        assert consumer.events_consumed == 1
        assert consumer.invocations == 1
        assert len(consumer.collected_findings) >= 1

    @pytest.mark.asyncio
    async def test_batch_accumulates(self, queue, cluster_graph):
        """Events accumulate until batch_size is reached."""
        for i in range(5):
            await queue.put(_make_event(f"s{i}"))

        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=5,
        )
        await consumer.run(max_events=5)
        assert consumer.events_consumed == 5
        assert consumer.invocations == 1

    @pytest.mark.asyncio
    async def test_partial_batch_flushed_on_stop(self, queue, cluster_graph):
        """Partial batches are flushed when the consumer stops."""
        for i in range(3):
            await queue.put(_make_event(f"s{i}"))

        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=10,
        )
        await consumer.run(max_events=3)
        assert consumer.events_consumed == 3
        assert consumer.invocations == 1  # partial batch flushed

    @pytest.mark.asyncio
    async def test_multiple_clusters(self, queue, cluster_graph):
        """Events from different clusters invoke separate agents."""
        await queue.put(_make_event("s1", cluster_id="cluster-north"))
        await queue.put(_make_event("s2", cluster_id="cluster-south"))

        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=1,
        )
        await consumer.run(max_events=2)
        assert consumer.events_consumed == 2
        assert consumer.invocations == 2

        cluster_ids = {f["cluster_id"] for f in consumer.collected_findings}
        assert "cluster-north" in cluster_ids
        assert "cluster-south" in cluster_ids

    @pytest.mark.asyncio
    async def test_on_finding_callback(self, queue, cluster_graph):
        await queue.put(_make_event())
        callback_log = []

        consumer = EventBridgeConsumer(
            queue=queue,
            agent_graph=cluster_graph,
            on_finding=lambda f: callback_log.append(f),
            batch_size=1,
        )
        await consumer.run(max_events=1)
        assert len(callback_log) >= 1
        assert callback_log[0]["cluster_id"] == "cluster-north"

    @pytest.mark.asyncio
    async def test_stop_terminates(self, queue, cluster_graph):
        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=1,
        )

        async def stop_soon():
            await asyncio.sleep(0.1)
            consumer.stop()

        asyncio.create_task(stop_soon())
        await consumer.run()
        # Should return without hanging.

    @pytest.mark.asyncio
    async def test_empty_queue_stop(self, queue, cluster_graph):
        """Consumer stops gracefully on an empty queue."""
        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=1,
        )
        await consumer.run(max_events=0)
        assert consumer.events_consumed == 0
        assert consumer.invocations == 0

    @pytest.mark.asyncio
    async def test_findings_accumulate_across_batches(self, queue, cluster_graph):
        for i in range(6):
            await queue.put(_make_event(f"s{i}"))

        consumer = EventBridgeConsumer(
            queue=queue, agent_graph=cluster_graph, batch_size=3,
        )
        await consumer.run(max_events=6)
        assert consumer.invocations == 2
        assert len(consumer.collected_findings) >= 2


class TestPublisherEngineTick:
    """Tests that SensorPublisher advances WorldEngine when wired."""

    @pytest.mark.asyncio
    async def test_publisher_ticks_engine(self):
        from sensors import SensorPublisher
        from sensors.base import SensorBase
        from domains.wildfire import FirePhysicsModule
        from domains.wildfire.environment import FireEnvironmentState
        from world import GenericWorldEngine
        from world.generic_grid import GenericTerrainGrid

        physics = FirePhysicsModule(base_probability=0.0)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState(temp_drift=0.0, humidity_drift=0.0,
                                   wind_speed_drift=0.0, wind_direction_drift=0.0,
                                   pressure_drift=0.0)
        engine = GenericWorldEngine(grid=grid, environment=env, physics=physics)

        class _Stub(SensorBase):
            source_type = "stub"
            def read(self):
                return {"v": 1}

        q = SensorEventQueue()
        sensor = _Stub(source_id="s1", cluster_id="c1")
        pub = SensorPublisher(
            sensors=[sensor], queue=q, tick_interval_seconds=0.0, engine=engine,
        )

        assert engine.current_tick == 0
        await pub.run(ticks=5)
        assert engine.current_tick == 5
        assert q.total_enqueued == 5

    @pytest.mark.asyncio
    async def test_publisher_without_engine_unchanged(self):
        from sensors import SensorPublisher
        from sensors.base import SensorBase

        class _Stub(SensorBase):
            source_type = "stub"
            def read(self):
                return {"v": 1}

        q = SensorEventQueue()
        sensor = _Stub(source_id="s1", cluster_id="c1")
        pub = SensorPublisher(
            sensors=[sensor], queue=q, tick_interval_seconds=0.0,
        )

        await pub.run(ticks=3)
        assert q.total_enqueued == 3
