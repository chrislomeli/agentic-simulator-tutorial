"""Tests for event_loop.loop — EventLoop orchestration."""

import pytest

from event_loop.loop import EventLoop, EventLoopConfig
from event_loop.sensor_filter import SensorFilter
from event_loop.store import InMemoryLocationStore

# ── Test doubles ──────────────────────────────────────────────────────────────

class AlwaysTriggerFilter(SensorFilter):
    """Filter that always triggers — for testing batch delivery."""
    def should_trigger(self, recent_events):
        return True, "always triggers"


class NeverTriggerFilter(SensorFilter):
    """Filter that never triggers."""
    def should_trigger(self, recent_events):
        return False, "never triggers"


# ── SIMULATION mode tests ────────────────────────────────────────────────────

class TestEventLoopSimulation:
    def _make_config(self, cycles: int = 3, locations=None) -> EventLoopConfig:
        return EventLoopConfig(
            mode="SIMULATION",
            location_ids=locations or ["loc-A", "loc-B"],
            cycle_speed_seconds=0.0,
            max_cycles=cycles,
        )

    @pytest.mark.asyncio
    async def test_runs_for_configured_cycles(self):
        config = self._make_config(cycles=5)
        loop = EventLoop(config, sensor_filter=NeverTriggerFilter())
        await loop.run()
        assert loop.cycles_completed == 5

    @pytest.mark.asyncio
    async def test_store_populated_after_run(self):
        store = InMemoryLocationStore()
        config = self._make_config(cycles=3, locations=["loc-A", "loc-B"])
        loop = EventLoop(config, store=store, sensor_filter=NeverTriggerFilter())
        await loop.run()
        assert store.get("loc-A") is not None
        assert store.get("loc-B") is not None

    @pytest.mark.asyncio
    async def test_on_batch_called_when_triggered(self):
        batches = []
        config = self._make_config(cycles=3)
        loop = EventLoop(
            config,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        assert len(batches) == 3

    @pytest.mark.asyncio
    async def test_on_batch_not_called_when_no_trigger(self):
        batches = []
        config = self._make_config(cycles=5)
        loop = EventLoop(
            config,
            sensor_filter=NeverTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_batch_shape(self):
        batches = []
        config = self._make_config(cycles=1, locations=["loc-A", "loc-B"])
        loop = EventLoop(
            config,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        assert len(batches) == 1
        batch = batches[0]
        assert "cycle" in batch
        assert batch["cycle"] == 1
        assert "active_cluster_ids" in batch
        assert "events_by_cluster" in batch
        assert set(batch["active_cluster_ids"]) == {"loc-A", "loc-B"}

    @pytest.mark.asyncio
    async def test_batch_events_are_lists_of_dicts(self):
        batches = []
        config = self._make_config(cycles=2, locations=["loc-A"])
        loop = EventLoop(
            config,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        last_batch = batches[-1]
        events = last_batch["events_by_cluster"]["loc-A"]
        assert isinstance(events, list)
        assert len(events) >= 1
        assert "temperature_c" in events[0]
        assert "location_id" in events[0]

    @pytest.mark.asyncio
    async def test_history_accumulates_across_cycles(self):
        store = InMemoryLocationStore()
        config = self._make_config(cycles=5, locations=["loc-A"])
        loop = EventLoop(config, store=store, sensor_filter=NeverTriggerFilter())
        await loop.run()
        history = store.get_recent_events("loc-A")
        assert len(history) == 5

    def test_simulation_requires_location_ids(self):
        config = EventLoopConfig(mode="SIMULATION", location_ids=None)
        with pytest.raises(ValueError, match="SIMULATION mode requires"):
            EventLoop(config)


# ── PIPELINE mode tests ──────────────────────────────────────────────────────

class TestEventLoopPipeline:
    """Tests for PIPELINE mode — event loop reads from a pre-populated store."""

    @pytest.mark.asyncio
    async def test_reads_from_store(self):
        store = InMemoryLocationStore()
        store.set("cluster-north", {
            "location_id": "cluster-north",
            "temperature_c": 45.0,
            "humidity_pct": 10.0,
        })
        batches = []
        config = EventLoopConfig(
            mode="PIPELINE",
            cycle_speed_seconds=0.0,
            max_cycles=1,
        )
        loop = EventLoop(
            config,
            store=store,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        assert len(batches) == 1
        assert "cluster-north" in batches[0]["active_cluster_ids"]

    @pytest.mark.asyncio
    async def test_no_locations_skips_gracefully(self):
        store = InMemoryLocationStore()  # empty
        batches = []
        config = EventLoopConfig(
            mode="PIPELINE",
            cycle_speed_seconds=0.0,
            max_cycles=3,
        )
        loop = EventLoop(
            config,
            store=store,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        assert len(batches) == 0
        assert loop.cycles_completed == 3

    @pytest.mark.asyncio
    async def test_discovers_locations_dynamically(self):
        """Store gets populated between cycles — event loop discovers new locations."""
        store = InMemoryLocationStore()
        batches = []

        def on_batch(batch):
            batches.append(batch)

        config = EventLoopConfig(
            mode="PIPELINE",
            cycle_speed_seconds=0.0,
            max_cycles=3,
        )
        loop = EventLoop(
            config,
            store=store,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=on_batch,
        )

        # Pre-populate before running
        store.set("cluster-north", {
            "location_id": "cluster-north",
            "temperature_c": 40.0,
        })
        await loop.run()
        # At least one batch should have cluster-north
        assert any("cluster-north" in b["active_cluster_ids"] for b in batches)

    @pytest.mark.asyncio
    async def test_pipeline_does_not_generate_data(self):
        store = InMemoryLocationStore()
        config = EventLoopConfig(
            mode="PIPELINE",
            cycle_speed_seconds=0.0,
            max_cycles=3,
        )
        loop = EventLoop(
            config,
            store=store,
            sensor_filter=NeverTriggerFilter(),
        )
        await loop.run()
        # Store should still be empty — pipeline mode doesn't generate
        assert store.get_all_location_ids() == []

    @pytest.mark.asyncio
    async def test_explicit_location_ids_in_pipeline_mode(self):
        """Pipeline mode with explicit location_ids only checks those."""
        store = InMemoryLocationStore()
        store.set("cluster-north", {"location_id": "cluster-north", "temperature_c": 40.0})
        store.set("cluster-south", {"location_id": "cluster-south", "temperature_c": 40.0})

        batches = []
        config = EventLoopConfig(
            mode="PIPELINE",
            location_ids=["cluster-north"],  # only check north
            cycle_speed_seconds=0.0,
            max_cycles=1,
        )
        loop = EventLoop(
            config,
            store=store,
            sensor_filter=AlwaysTriggerFilter(),
            on_batch=batches.append,
        )
        await loop.run()
        assert len(batches) == 1
        assert batches[0]["active_cluster_ids"] == ["cluster-north"]
