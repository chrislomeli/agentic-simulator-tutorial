"""Tests for world-simiulator.sensors.publisher — SensorPublisher async loop."""

import asyncio

import pytest

from world.sensors import SensorPublisher
from world.sensors.base import FailureMode, SensorBase
from world.transport import SensorEvent, SensorEventQueue
from world.sensor_inventory import SensorInventory


class _FakeSensor(SensorBase):
    source_type = "fake"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._call_count = 0

    def read(self, local_conditions=None):
        self._call_count += 1
        return {"count": self._call_count}


def _make_inventory(sensors: list[SensorBase]) -> SensorInventory:
    inv = SensorInventory(grid_rows=10, grid_cols=10)
    for sensor in sensors:
        inv.register_auto(sensor)
    return inv


@pytest.fixture
def event_queue():
    return SensorEventQueue(maxsize=100)


@pytest.fixture
def sensors():
    return [
        _FakeSensor(source_id="f1", cluster_id="c1", grid_row=0, grid_col=0),
        _FakeSensor(source_id="f2", cluster_id="c1", grid_row=1, grid_col=1),
    ]


@pytest.fixture
def inventory(sensors):
    return _make_inventory(sensors)


class TestSensorPublisher:
    @pytest.mark.asyncio
    async def test_run_produces_events(self, inventory, event_queue):
        pub = SensorPublisher(
            inventory=inventory,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=3, location_count=None)
        assert event_queue.qsize() == 6  # 2 sensors × 3 ticks

    @pytest.mark.asyncio
    async def test_events_are_sensor_events(self, inventory, event_queue):
        pub = SensorPublisher(
            inventory=inventory,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=1, location_count=None)
        event = await event_queue.get()
        assert isinstance(event, SensorEvent)

    @pytest.mark.asyncio
    async def test_dropout_sensor_skipped(self, sensors, event_queue):
        sensors[0].set_failure_mode(FailureMode.DROPOUT)
        pub = SensorPublisher(
            inventory=_make_inventory(sensors),
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=2, location_count=None)
        assert event_queue.qsize() == 2  # only sensor[1] produces events

    @pytest.mark.asyncio
    async def test_stop_terminates(self, inventory, event_queue):
        pub = SensorPublisher(
            inventory=inventory,
            queue=event_queue,
            tick_interval_seconds=0.01,
        )

        async def stop_after():
            await asyncio.sleep(0.05)
            pub.stop()

        asyncio.create_task(stop_after())
        await pub.run(location_count=None)
        assert event_queue.qsize() > 0

    @pytest.mark.asyncio
    async def test_zero_ticks(self, inventory, event_queue):
        pub = SensorPublisher(
            inventory=inventory,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=0, location_count=None)
        assert event_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_single_sensor(self, event_queue):
        sensor = _FakeSensor(source_id="solo", cluster_id="c1", grid_row=0, grid_col=0)
        pub = SensorPublisher(
            inventory=_make_inventory([sensor]),
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=5, location_count=None)
        assert event_queue.qsize() == 5

    @pytest.mark.asyncio
    async def test_random_location_sampling(self, event_queue):
        # Five sensors at five distinct locations; sample 2 per tick.
        sensors = [
            _FakeSensor(source_id=f"f{i}", cluster_id="c1", grid_row=i, grid_col=0)
            for i in range(5)
        ]
        pub = SensorPublisher(
            inventory=_make_inventory(sensors),
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=3, location_count=2)
        assert event_queue.qsize() == 6  # 2 locations × 3 ticks
