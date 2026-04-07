"""Tests for ogar.world.sensor_inventory — SensorInventory."""

import pytest

from sensors.base import FailureMode, SensorBase
from world.sensor_inventory import SensorInventory


# ── Minimal sensor for testing ───────────────────────────────────────────────

class StubSensor(SensorBase):
    """Trivial sensor that returns a fixed reading."""
    source_type = "stub"

    def __init__(self, source_id: str, cluster_id: str = "cluster-test", **kwargs):
        super().__init__(source_id=source_id, cluster_id=cluster_id, **kwargs)

    def read(self):
        return {"value": 42}


class StubSensorB(SensorBase):
    """Second sensor type for layer tests."""
    source_type = "stub_b"

    def __init__(self, source_id: str, cluster_id: str = "cluster-test", **kwargs):
        super().__init__(source_id=source_id, cluster_id=cluster_id, **kwargs)

    def read(self):
        return {"value": 99}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def inventory():
    return SensorInventory(grid_rows=5, grid_cols=5)


@pytest.fixture
def sensors():
    """Create a batch of 10 sensors with predictable IDs."""
    return [StubSensor(source_id=f"sensor-{i}") for i in range(10)]


# ── Registration tests ───────────────────────────────────────────────────────

class TestRegistration:
    def test_register_and_get(self, inventory):
        s = StubSensor(source_id="s1")
        inventory.register(s, row=2, col=3)
        assert inventory.get_sensor("s1") is s
        assert inventory.get_position("s1") == (2, 3, 0)

    def test_register_duplicate_raises(self, inventory):
        s = StubSensor(source_id="s1")
        inventory.register(s, row=0, col=0)
        with pytest.raises(ValueError, match="already registered"):
            inventory.register(s, row=1, col=1)

    def test_register_out_of_bounds_raises(self, inventory):
        s = StubSensor(source_id="s1")
        with pytest.raises(ValueError, match="out of bounds"):
            inventory.register(s, row=5, col=0)

    def test_unregister(self, inventory):
        s = StubSensor(source_id="s1")
        inventory.register(s, row=0, col=0)
        removed = inventory.unregister("s1")
        assert removed is s
        assert inventory.size == 0
        with pytest.raises(KeyError):
            inventory.get_sensor("s1")

    def test_unregister_unknown_raises(self, inventory):
        with pytest.raises(KeyError):
            inventory.unregister("nonexistent")


# ── Query tests ──────────────────────────────────────────────────────────────

class TestQueries:
    def test_get_sensors_at(self, inventory):
        s1 = StubSensor(source_id="s1")
        s2 = StubSensor(source_id="s2")
        s3 = StubSensor(source_id="s3")
        inventory.register(s1, row=1, col=1)
        inventory.register(s2, row=1, col=1)  # co-located
        inventory.register(s3, row=2, col=2)

        at_1_1 = inventory.get_sensors_at(1, 1)
        assert len(at_1_1) == 2
        assert s1 in at_1_1
        assert s2 in at_1_1

    def test_all_sensors(self, inventory, sensors):
        for i, s in enumerate(sensors[:3]):
            inventory.register(s, row=i, col=0)
        assert len(inventory.all_sensors()) == 3

    def test_size(self, inventory):
        assert inventory.size == 0
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        assert inventory.size == 1


# ── Coverage tests ───────────────────────────────────────────────────────────

class TestCoverage:
    def test_coverage_ratio_empty(self, inventory):
        assert inventory.coverage_ratio() == 0.0

    def test_coverage_ratio_partial(self, inventory):
        # 5x5 grid = 25 cells, 5 sensors at unique positions = 20% coverage
        for i in range(5):
            inventory.register(StubSensor(source_id=f"s{i}"), row=i, col=0)
        assert inventory.coverage_ratio() == pytest.approx(5 / 25)

    def test_colocated_sensors_count_once(self, inventory):
        # Two sensors at same position = 1 covered cell
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensor(source_id="s2"), row=0, col=0)
        assert inventory.coverage_ratio() == pytest.approx(1 / 25)

    def test_covered_cells(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=1, col=2)
        inventory.register(StubSensor(source_id="s2"), row=3, col=4)
        assert inventory.covered_cells() == {(1, 2, 0), (3, 4, 0)}


# ── Thinning tests ───────────────────────────────────────────────────────────

class TestThinning:
    def test_thin_removes_sensors(self, inventory, sensors):
        for i, s in enumerate(sensors):
            inventory.register(s, row=i % 5, col=i // 5)

        removed = inventory.thin(keep_fraction=0.5)
        assert len(removed) == 5
        assert inventory.size == 5

    def test_thin_keep_all(self, inventory, sensors):
        for i, s in enumerate(sensors[:3]):
            inventory.register(s, row=i, col=0)
        removed = inventory.thin(keep_fraction=1.0)
        assert len(removed) == 0
        assert inventory.size == 3

    def test_thin_remove_all(self, inventory, sensors):
        for i, s in enumerate(sensors[:3]):
            inventory.register(s, row=i, col=0)
        removed = inventory.thin(keep_fraction=0.0)
        assert len(removed) == 3
        assert inventory.size == 0

    def test_thin_invalid_fraction(self, inventory):
        with pytest.raises(ValueError):
            inventory.thin(keep_fraction=1.5)


# ── Failure injection tests ──────────────────────────────────────────────────

class TestFailureInjection:
    def test_inject_failure_single(self, inventory):
        s = StubSensor(source_id="s1")
        inventory.register(s, row=0, col=0)
        inventory.inject_failure("s1", FailureMode.STUCK)
        assert s._failure_mode == FailureMode.STUCK

    def test_inject_failure_unknown_raises(self, inventory):
        with pytest.raises(KeyError):
            inventory.inject_failure("nonexistent", FailureMode.STUCK)

    def test_inject_bulk_failure(self, inventory, sensors):
        for i, s in enumerate(sensors):
            inventory.register(s, row=i % 5, col=i // 5)

        affected = inventory.inject_bulk_failure(FailureMode.DROPOUT, fraction=0.5)
        assert len(affected) == 5
        dropout_count = sum(
            1 for s in inventory.all_sensors()
            if s._failure_mode == FailureMode.DROPOUT
        )
        assert dropout_count == 5

    def test_reset_all_failures(self, inventory, sensors):
        for i, s in enumerate(sensors[:3]):
            inventory.register(s, row=i, col=0)
        inventory.inject_bulk_failure(FailureMode.DRIFT, fraction=1.0)
        inventory.reset_all_failures()
        for s in inventory.all_sensors():
            assert s._failure_mode == FailureMode.NORMAL


# ── Emission tests ───────────────────────────────────────────────────────────

class TestEmission:
    def test_emit_all(self, inventory):
        s1 = StubSensor(source_id="s1")
        s2 = StubSensor(source_id="s2")
        inventory.register(s1, row=0, col=0)
        inventory.register(s2, row=1, col=1)

        events = inventory.emit_all()
        assert len(events) == 2
        source_ids = {e.source_id for e in events}
        assert source_ids == {"s1", "s2"}

    def test_emit_all_skips_dropout(self, inventory):
        s1 = StubSensor(source_id="s1")
        s2 = StubSensor(source_id="s2")
        inventory.register(s1, row=0, col=0)
        inventory.register(s2, row=1, col=1)
        inventory.inject_failure("s1", FailureMode.DROPOUT)

        events = inventory.emit_all()
        assert len(events) == 1
        assert events[0].source_id == "s2"


# ── Repr test ────────────────────────────────────────────────────────────────

class TestRepr:
    def test_repr(self, inventory):
        r = repr(inventory)
        assert "SensorInventory" in r
        assert "5×5×1" in r


# ── Auto-registration tests ─────────────────────────────────────────────────

class TestRegisterAuto:
    def test_register_auto(self, inventory):
        s = StubSensor(source_id="s1", grid_row=2, grid_col=3)
        inventory.register_auto(s)
        assert inventory.get_position("s1") == (2, 3, 0)

    def test_register_auto_no_location_raises(self, inventory):
        s = StubSensor(source_id="s1")
        with pytest.raises(ValueError, match="no grid location"):
            inventory.register_auto(s)


# ── Layer tests ─────────────────────────────────────────────────────────────

class TestLayers:
    def test_layer_types(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensorB(source_id="b1"), row=1, col=1)
        assert inventory.layer_types() == {"stub", "stub_b"}

    def test_layer_types_empty(self, inventory):
        assert inventory.layer_types() == set()

    def test_get_layer(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensor(source_id="s2"), row=1, col=1)
        inventory.register(StubSensorB(source_id="b1"), row=2, col=2)

        layer = inventory.get_layer("stub")
        assert layer == {"s1": (0, 0, 0), "s2": (1, 1, 0)}

    def test_get_layer_empty(self, inventory):
        assert inventory.get_layer("nonexistent") == {}

    def test_layer_positions(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensor(source_id="s2"), row=1, col=1)
        assert inventory.layer_positions("stub") == {(0, 0, 0), (1, 1, 0)}

    def test_all_layer_positions(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensorB(source_id="b1"), row=2, col=2)
        result = inventory.all_layer_positions()
        assert result == {"stub": {(0, 0, 0)}, "stub_b": {(2, 2, 0)}}

    def test_layer_coverage_ratio(self, inventory):
        # 5x5 = 25 cells, 2 stub sensors at unique positions = 8%
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensor(source_id="s2"), row=1, col=1)
        assert inventory.layer_coverage_ratio("stub") == pytest.approx(2 / 25)
        assert inventory.layer_coverage_ratio("stub_b") == 0.0

    def test_unregister_updates_type_index(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.register(StubSensor(source_id="s2"), row=1, col=1)
        inventory.unregister("s1")
        assert inventory.get_layer("stub") == {"s2": (1, 1, 0)}

    def test_unregister_last_of_type_removes_layer(self, inventory):
        inventory.register(StubSensor(source_id="s1"), row=0, col=0)
        inventory.unregister("s1")
        assert "stub" not in inventory.layer_types()


class TestLayerExperiments:
    def test_thin_layer(self, inventory):
        for i in range(6):
            inventory.register(StubSensor(source_id=f"s{i}"), row=i % 5, col=i // 5)
        inventory.register(StubSensorB(source_id="b1"), row=4, col=4)

        removed = inventory.thin_layer("stub", keep_fraction=0.5)
        assert len(removed) == 3
        # StubSensorB should be untouched
        assert inventory.get_sensor("b1") is not None

    def test_inject_layer_failure(self, inventory):
        for i in range(4):
            inventory.register(StubSensor(source_id=f"s{i}"), row=i, col=0)
        inventory.register(StubSensorB(source_id="b1"), row=4, col=0)

        affected = inventory.inject_layer_failure("stub", FailureMode.STUCK, fraction=0.5)
        assert len(affected) == 2
        # StubSensorB should remain NORMAL
        assert inventory.get_sensor("b1")._failure_mode == FailureMode.NORMAL
