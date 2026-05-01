"""Tests for ogar.bridge.consumer — EventBridgeConsumer."""

import asyncio

import pytest

from bridge.consumer import EventBridgeConsumer
from event_loop.store import InMemoryLocationStore
from transport import SensorEvent, SensorEventQueue


def _make_event(
    source_id: str = "s1",
    cluster_id: str = "cluster-north",
    source_type: str = "temperature",
    payload: dict | None = None,
) -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id,
        source_type=source_type,
        cluster_id=cluster_id,
        payload=payload or {"celsius": 42.0},
    )


@pytest.fixture
def queue():
    return SensorEventQueue(maxsize=100)


@pytest.fixture
def store():
    return InMemoryLocationStore()


class TestEventBridgeConsumer:
    @pytest.mark.asyncio
    async def test_consume_single_event(self, queue, store):
        await queue.put(_make_event())
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=1)
        assert consumer.events_consumed == 1
        assert "cluster-north" in consumer.events_by_cluster
        assert len(consumer.events_by_cluster["cluster-north"]) == 1

    @pytest.mark.asyncio
    async def test_groups_events_by_cluster(self, queue, store):
        for i in range(5):
            await queue.put(_make_event(f"s{i}"))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=5)
        assert consumer.events_consumed == 5
        assert len(consumer.events_by_cluster["cluster-north"]) == 5

    @pytest.mark.asyncio
    async def test_multiple_clusters(self, queue, store):
        await queue.put(_make_event("s1", cluster_id="cluster-north"))
        await queue.put(_make_event("s2", cluster_id="cluster-south"))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=2)
        assert consumer.events_consumed == 2
        assert "cluster-north" in consumer.events_by_cluster
        assert "cluster-south" in consumer.events_by_cluster
        assert len(consumer.events_by_cluster["cluster-north"]) == 1
        assert len(consumer.events_by_cluster["cluster-south"]) == 1

    @pytest.mark.asyncio
    async def test_stop_terminates(self, queue, store):
        consumer = EventBridgeConsumer(queue=queue, store=store)

        async def stop_soon():
            await asyncio.sleep(0.1)
            consumer.stop()

        asyncio.create_task(stop_soon())
        await consumer.run()
        # Should return without hanging.

    @pytest.mark.asyncio
    async def test_empty_queue_stop(self, queue, store):
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=0)
        assert consumer.events_consumed == 0
        assert consumer.events_by_cluster == {}

    @pytest.mark.asyncio
    async def test_events_preserve_order(self, queue, store):
        for i in range(4):
            await queue.put(_make_event(f"s{i}"))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=4)
        events = consumer.events_by_cluster["cluster-north"]
        source_ids = [e.source_id for e in events]
        assert source_ids == ["s0", "s1", "s2", "s3"]


class TestConsumerStoreAggregation:
    """Tests for the consumer → LocationStateStore aggregation path."""

    @pytest.mark.asyncio
    async def test_writes_temperature_to_store(self, queue, store):
        await queue.put(_make_event(source_type="temperature", payload={"celsius": 42.0}))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=1)
        state = store.get("cluster-north")
        assert state is not None
        assert state["temperature_c"] == 42.0
        assert state["location_id"] == "cluster-north"

    @pytest.mark.asyncio
    async def test_writes_humidity_to_store(self, queue, store):
        await queue.put(_make_event(
            source_type="humidity",
            payload={"relative_humidity_pct": 25.0},
        ))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=1)
        state = store.get("cluster-north")
        assert state["humidity_pct"] == 25.0

    @pytest.mark.asyncio
    async def test_writes_wind_to_store(self, queue, store):
        await queue.put(_make_event(
            source_type="wind",
            payload={"speed_mps": 8.5, "direction_deg": 180.0},
        ))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=1)
        state = store.get("cluster-north")
        assert state["wind_speed_mps"] == 8.5
        assert state["wind_direction_deg"] == 180.0

    @pytest.mark.asyncio
    async def test_merges_multiple_sensor_types(self, queue, store):
        """Multiple sensor types merge into one composite location state."""
        await queue.put(_make_event(source_type="temperature", payload={"celsius": 40.0}))
        await queue.put(_make_event(source_type="humidity", payload={"relative_humidity_pct": 12.0}))
        await queue.put(_make_event(source_type="wind", payload={"speed_mps": 15.0}))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=3)
        state = store.get("cluster-north")
        assert state["temperature_c"] == 40.0
        assert state["humidity_pct"] == 12.0
        assert state["wind_speed_mps"] == 15.0

    @pytest.mark.asyncio
    async def test_multiple_clusters_write_separate_states(self, queue, store):
        await queue.put(_make_event(cluster_id="cluster-north", payload={"celsius": 35.0}))
        await queue.put(_make_event(cluster_id="cluster-south", payload={"celsius": 28.0}))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=2)
        north = store.get("cluster-north")
        south = store.get("cluster-south")
        assert north["temperature_c"] == 35.0
        assert south["temperature_c"] == 28.0

    @pytest.mark.asyncio
    async def test_history_accumulates(self, queue, store):
        """Successive events for the same location build history."""
        for temp in [30.0, 32.0, 35.0]:
            await queue.put(_make_event(payload={"celsius": temp}))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=3)
        history = store.get_recent_events("cluster-north", n=10)
        assert len(history) == 3
        assert history[0]["temperature_c"] == 30.0
        assert history[2]["temperature_c"] == 35.0

    @pytest.mark.asyncio
    async def test_store_location_ids(self, queue, store):
        await queue.put(_make_event(cluster_id="cluster-north"))
        await queue.put(_make_event(cluster_id="cluster-south"))
        consumer = EventBridgeConsumer(queue=queue, store=store)
        await consumer.run(max_events=2)
        ids = store.get_all_location_ids()
        assert set(ids) == {"cluster-north", "cluster-south"}


class TestPublisherEngineTick:
    """Tests that SensorPublisher advances WorldEngine when wired."""

    @pytest.mark.asyncio
    async def test_publisher_ticks_engine(self):
        from domains.wildfire import FirePhysicsModule
        from domains.wildfire.environment import FireEnvironmentState
        from sensors import SensorPublisher
        from sensors.base import SensorBase
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
            def read(self, local_conditions=None):
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
            def read(self, local_conditions=None):
                return {"v": 1}

        q = SensorEventQueue()
        sensor = _Stub(source_id="s1", cluster_id="c1")
        pub = SensorPublisher(
            sensors=[sensor], queue=q, tick_interval_seconds=0.0,
        )

        await pub.run(ticks=3)
        assert q.total_enqueued == 3
