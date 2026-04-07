"""Tests for ogar.sensors.publisher — SensorPublisher async loop."""

import asyncio

import pytest

from sensors.base import SensorBase, FailureMode
from sensors import SensorPublisher
from transport import SensorEventQueue
from transport import SensorEvent
from world.sensor_inventory import SensorInventory


class _FakeSensor(SensorBase):
    source_type = "fake"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._call_count = 0

    def read(self):
        self._call_count += 1
        return {"count": self._call_count}


@pytest.fixture
def event_queue():
    return SensorEventQueue(maxsize=100)


@pytest.fixture
def sensors():
    return [
        _FakeSensor(source_id="f1", cluster_id="c1"),
        _FakeSensor(source_id="f2", cluster_id="c1"),
    ]


class TestSensorPublisher:
    @pytest.mark.asyncio
    async def test_run_produces_events(self, sensors, event_queue):
        pub = SensorPublisher(
            sensors=sensors,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=3)
        assert event_queue.qsize() == 6  # 2 sensors × 3 ticks

    @pytest.mark.asyncio
    async def test_events_are_sensor_events(self, sensors, event_queue):
        pub = SensorPublisher(
            sensors=sensors,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=1)
        event = await event_queue.get()
        assert isinstance(event, SensorEvent)

    @pytest.mark.asyncio
    async def test_dropout_sensor_skipped(self, sensors, event_queue):
        sensors[0].set_failure_mode(FailureMode.DROPOUT)
        pub = SensorPublisher(
            sensors=sensors,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=2)
        assert event_queue.qsize() == 2  # only sensor[1] produces events

    @pytest.mark.asyncio
    async def test_stop_terminates(self, sensors, event_queue):
        pub = SensorPublisher(
            sensors=sensors,
            queue=event_queue,
            tick_interval_seconds=0.01,
        )

        async def stop_after():
            await asyncio.sleep(0.05)
            pub.stop()

        asyncio.create_task(stop_after())
        await pub.run()
        assert event_queue.qsize() > 0

    @pytest.mark.asyncio
    async def test_zero_ticks(self, sensors, event_queue):
        pub = SensorPublisher(
            sensors=sensors,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=0)
        assert event_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_single_sensor(self, event_queue):
        sensor = _FakeSensor(source_id="solo", cluster_id="c1")
        pub = SensorPublisher(
            sensors=[sensor],
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=5)
        assert event_queue.qsize() == 5

    @pytest.mark.asyncio
    async def test_inventory_based(self, event_queue):
        inv = SensorInventory(grid_rows=5, grid_cols=5)
        s1 = _FakeSensor(source_id="f1", cluster_id="c1", grid_row=0, grid_col=0)
        s2 = _FakeSensor(source_id="f2", cluster_id="c1", grid_row=1, grid_col=1)
        inv.register_auto(s1)
        inv.register_auto(s2)

        pub = SensorPublisher(
            inventory=inv,
            queue=event_queue,
            tick_interval_seconds=0.0,
        )
        await pub.run(ticks=3)
        assert event_queue.qsize() == 6  # 2 sensors × 3 ticks

    @pytest.mark.asyncio
    async def test_no_sensors_or_inventory_raises(self, event_queue):
        with pytest.raises(ValueError, match="Provide either"):
            SensorPublisher(queue=event_queue)
