"""Tests for ogar.transport.queue — SensorEventQueue async."""

import asyncio

import pytest

from transport import SensorEventQueue
from transport import SensorEvent


@pytest.fixture
def queue():
    return SensorEventQueue()


@pytest.fixture
def bounded_queue():
    return SensorEventQueue(maxsize=2)


def _make_event(source_id: str = "s1") -> SensorEvent:
    return SensorEvent.create(
        source_id=source_id, source_type="t", cluster_id="c1", payload={"v": 1}
    )


class TestSensorEventQueue:
    @pytest.mark.asyncio
    async def test_put_and_get(self, queue):
        event = _make_event()
        await queue.put(event)
        got = await queue.get()
        assert got.event_id == event.event_id

    @pytest.mark.asyncio
    async def test_fifo_order(self, queue):
        e1 = _make_event("first")
        e2 = _make_event("second")
        await queue.put(e1)
        await queue.put(e2)
        got1 = await queue.get()
        got2 = await queue.get()
        assert got1.source_id == "first"
        assert got2.source_id == "second"

    @pytest.mark.asyncio
    async def test_qsize(self, queue):
        assert queue.qsize() == 0
        await queue.put(_make_event())
        assert queue.qsize() == 1
        await queue.get()
        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_empty(self, queue):
        assert queue.empty() is True
        await queue.put(_make_event())
        assert queue.empty() is False

    @pytest.mark.asyncio
    async def test_total_enqueued(self, queue):
        assert queue.total_enqueued == 0
        await queue.put(_make_event())
        await queue.put(_make_event())
        assert queue.total_enqueued == 2

    @pytest.mark.asyncio
    async def test_task_done(self, queue):
        await queue.put(_make_event())
        await queue.get()
        queue.task_done()
        await asyncio.wait_for(queue.join(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_join_blocks_until_done(self, queue):
        await queue.put(_make_event())

        async def consumer():
            await asyncio.sleep(0.05)
            await queue.get()
            queue.task_done()

        asyncio.create_task(consumer())
        await asyncio.wait_for(queue.join(), timeout=2.0)
        assert queue.empty()
