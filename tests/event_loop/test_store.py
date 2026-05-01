"""Tests for event_loop.store — LocationStateStore implementations."""

import pytest
from event_loop.store import InMemoryLocationStore, RedisLocationStore


def _state(location_id: str = "loc-A", temp: float = 28.0) -> dict:
    return {
        "location_id": location_id,
        "temperature_c": temp,
        "humidity_pct": 35.0,
        "wind_speed_mps": 4.0,
        "wind_direction_deg": 180.0,
        "fuel_moisture_pct": 12.0,
        "slope_deg": 5.0,
        "timestamp": "2024-01-01T00:00:00Z",
    }


class TestInMemoryLocationStore:
    def test_get_unknown_returns_none(self):
        store = InMemoryLocationStore()
        assert store.get("loc-X") is None

    def test_set_and_get_current(self):
        store = InMemoryLocationStore()
        s = _state("loc-A", temp=30.0)
        store.set("loc-A", s)
        assert store.get("loc-A")["temperature_c"] == 30.0

    def test_set_overwrites_current(self):
        store = InMemoryLocationStore()
        store.set("loc-A", _state("loc-A", temp=28.0))
        store.set("loc-A", _state("loc-A", temp=45.0))
        assert store.get("loc-A")["temperature_c"] == 45.0

    def test_get_recent_events_empty(self):
        store = InMemoryLocationStore()
        assert store.get_recent_events("loc-X") == []

    def test_get_recent_events_returns_history(self):
        store = InMemoryLocationStore()
        for temp in [20.0, 25.0, 30.0]:
            store.set("loc-A", _state("loc-A", temp=temp))
        events = store.get_recent_events("loc-A")
        assert len(events) == 3
        assert events[0]["temperature_c"] == 20.0  # oldest first
        assert events[-1]["temperature_c"] == 30.0  # newest last

    def test_get_recent_events_respects_n(self):
        store = InMemoryLocationStore()
        for temp in range(15):
            store.set("loc-A", _state("loc-A", temp=float(temp)))
        events = store.get_recent_events("loc-A", n=5)
        assert len(events) == 5
        assert events[-1]["temperature_c"] == 14.0  # most recent

    def test_history_size_cap(self):
        store = InMemoryLocationStore(history_size=5)
        for i in range(10):
            store.set("loc-A", _state("loc-A", temp=float(i)))
        events = store.get_recent_events("loc-A", n=20)
        assert len(events) == 5
        assert events[-1]["temperature_c"] == 9.0

    def test_get_all_location_ids_empty(self):
        store = InMemoryLocationStore()
        assert store.get_all_location_ids() == []

    def test_get_all_location_ids(self):
        store = InMemoryLocationStore()
        store.set("loc-A", _state("loc-A"))
        store.set("loc-B", _state("loc-B"))
        ids = store.get_all_location_ids()
        assert set(ids) == {"loc-A", "loc-B"}

    def test_multiple_locations_independent(self):
        store = InMemoryLocationStore()
        store.set("loc-A", _state("loc-A", temp=30.0))
        store.set("loc-B", _state("loc-B", temp=20.0))
        assert store.get("loc-A")["temperature_c"] == 30.0
        assert store.get("loc-B")["temperature_c"] == 20.0
        assert len(store.get_recent_events("loc-A")) == 1
        assert len(store.get_recent_events("loc-B")) == 1


class TestRedisLocationStoreStub:
    """RedisLocationStore is a stub — verify it raises NotImplementedError."""

    def test_get_raises(self):
        store = RedisLocationStore()
        with pytest.raises(NotImplementedError):
            store.get("loc-A")

    def test_set_raises(self):
        store = RedisLocationStore()
        with pytest.raises(NotImplementedError):
            store.set("loc-A", _state())

    def test_get_recent_events_raises(self):
        store = RedisLocationStore()
        with pytest.raises(NotImplementedError):
            store.get_recent_events("loc-A")

    def test_get_all_location_ids_raises(self):
        store = RedisLocationStore()
        with pytest.raises(NotImplementedError):
            store.get_all_location_ids()
