"""Tests for ogar.resources.base — ResourceBase and ResourceStatus."""

import pytest

from resources.base import ResourceBase, ResourceStatus


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_resource(**overrides) -> ResourceBase:
    """Create a ResourceBase with sensible defaults, overriding as needed."""
    defaults = dict(
        resource_id="truck-1",
        resource_type="firetruck",
        cluster_id="cluster-south",
        grid_row=5,
        grid_col=3,
        capacity=500.0,
        available=500.0,
        mobile=True,
    )
    defaults.update(overrides)
    return ResourceBase(**defaults)


# ── Construction ─────────────────────────────────────────────────────────────

class TestResourceBaseConstruction:
    def test_create_with_defaults(self):
        r = _make_resource()
        assert r.resource_id == "truck-1"
        assert r.resource_type == "firetruck"
        assert r.cluster_id == "cluster-south"
        assert r.status == ResourceStatus.AVAILABLE
        assert r.grid_row == 5
        assert r.grid_col == 3
        assert r.capacity == 500.0
        assert r.available == 500.0
        assert r.mobile is True
        assert r.metadata == {}

    def test_create_fixed_resource(self):
        r = _make_resource(
            resource_id="hospital-1",
            resource_type="hospital",
            mobile=False,
            capacity=50.0,
            available=42.0,
            metadata={"unit": "beds"},
        )
        assert r.mobile is False
        assert r.capacity == 50.0
        assert r.available == 42.0
        assert r.metadata == {"unit": "beds"}

    def test_status_default_is_available(self):
        r = _make_resource()
        assert r.status == ResourceStatus.AVAILABLE

    def test_capacity_validation_non_negative(self):
        with pytest.raises(Exception):
            _make_resource(capacity=-1.0)

    def test_available_validation_non_negative(self):
        with pytest.raises(Exception):
            _make_resource(available=-1.0)


# ── Status transitions ──────────────────────────────────────────────────────

class TestStatusTransitions:
    def test_deploy_changes_status(self):
        r = _make_resource()
        r.deploy()
        assert r.status == ResourceStatus.DEPLOYED

    def test_deploy_mobile_updates_location(self):
        r = _make_resource(grid_row=0, grid_col=0, mobile=True)
        r.deploy(row=7, col=3)
        assert r.status == ResourceStatus.DEPLOYED
        assert r.grid_row == 7
        assert r.grid_col == 3

    def test_deploy_fixed_ignores_location(self):
        r = _make_resource(grid_row=5, grid_col=5, mobile=False)
        r.deploy(row=9, col=9)
        assert r.status == ResourceStatus.DEPLOYED
        assert r.grid_row == 5  # unchanged
        assert r.grid_col == 5  # unchanged

    def test_deploy_out_of_service_raises(self):
        r = _make_resource()
        r.disable()
        with pytest.raises(ValueError, match="OUT_OF_SERVICE"):
            r.deploy()

    def test_send_en_route_mobile(self):
        r = _make_resource(mobile=True)
        r.send_en_route(row=2, col=8)
        assert r.status == ResourceStatus.EN_ROUTE
        assert r.grid_row == 2
        assert r.grid_col == 8

    def test_send_en_route_fixed_raises(self):
        r = _make_resource(mobile=False)
        with pytest.raises(ValueError, match="not mobile"):
            r.send_en_route(row=1, col=1)

    def test_send_en_route_out_of_service_raises(self):
        r = _make_resource(mobile=True)
        r.disable()
        with pytest.raises(ValueError, match="OUT_OF_SERVICE"):
            r.send_en_route(row=1, col=1)

    def test_release(self):
        r = _make_resource()
        r.deploy()
        assert r.status == ResourceStatus.DEPLOYED
        r.release()
        assert r.status == ResourceStatus.AVAILABLE

    def test_disable(self):
        r = _make_resource()
        r.disable()
        assert r.status == ResourceStatus.OUT_OF_SERVICE


# ── Capacity management ─────────────────────────────────────────────────────

class TestCapacityManagement:
    def test_consume_reduces_available(self):
        r = _make_resource(capacity=500.0, available=500.0)
        actual = r.consume(100.0)
        assert actual == 100.0
        assert r.available == 400.0

    def test_consume_capped_at_available(self):
        r = _make_resource(capacity=500.0, available=50.0)
        actual = r.consume(200.0)
        assert actual == 50.0
        assert r.available == 0.0

    def test_consume_zero(self):
        r = _make_resource(capacity=500.0, available=500.0)
        actual = r.consume(0.0)
        assert actual == 0.0
        assert r.available == 500.0

    def test_restore_increases_available(self):
        r = _make_resource(capacity=500.0, available=300.0)
        actual = r.restore(100.0)
        assert actual == 100.0
        assert r.available == 400.0

    def test_restore_capped_at_capacity(self):
        r = _make_resource(capacity=500.0, available=450.0)
        actual = r.restore(200.0)
        assert actual == 50.0
        assert r.available == 500.0

    def test_restore_from_empty(self):
        r = _make_resource(capacity=500.0, available=0.0)
        actual = r.restore(500.0)
        assert actual == 500.0
        assert r.available == 500.0


# ── Derived properties ───────────────────────────────────────────────────────

class TestDerivedProperties:
    def test_utilization_full_capacity(self):
        r = _make_resource(capacity=500.0, available=500.0)
        assert r.utilization == 0.0

    def test_utilization_half_used(self):
        r = _make_resource(capacity=500.0, available=250.0)
        assert r.utilization == pytest.approx(0.5)

    def test_utilization_empty(self):
        r = _make_resource(capacity=500.0, available=0.0)
        assert r.utilization == 1.0

    def test_utilization_zero_capacity(self):
        r = _make_resource(capacity=0.0, available=0.0)
        assert r.utilization == 0.0

    def test_is_available_true(self):
        r = _make_resource(status=ResourceStatus.AVAILABLE, available=100.0)
        assert r.is_available is True

    def test_is_available_false_when_deployed(self):
        r = _make_resource()
        r.deploy()
        assert r.is_available is False

    def test_is_available_false_when_no_capacity(self):
        r = _make_resource(capacity=500.0, available=0.0)
        assert r.is_available is False


# ── Serialisation ────────────────────────────────────────────────────────────

class TestSerialisation:
    def test_to_summary_dict(self):
        r = _make_resource(capacity=500.0, available=250.0)
        d = r.to_summary_dict()
        assert d["resource_id"] == "truck-1"
        assert d["resource_type"] == "firetruck"
        assert d["cluster_id"] == "cluster-south"
        assert d["status"] == "AVAILABLE"
        assert d["grid_row"] == 5
        assert d["grid_col"] == 3
        assert d["capacity"] == 500.0
        assert d["available"] == 250.0
        assert d["utilization"] == 0.5
        assert d["mobile"] is True

    def test_repr(self):
        r = _make_resource()
        s = repr(r)
        assert "truck-1" in s
        assert "firetruck" in s
        assert "AVAILABLE" in s


# ── ResourceStatus enum ─────────────────────────────────────────────────────

class TestResourceStatus:
    def test_str_mixin(self):
        assert ResourceStatus.AVAILABLE == "AVAILABLE"
        assert ResourceStatus.DEPLOYED == "DEPLOYED"
        assert ResourceStatus.EN_ROUTE == "EN_ROUTE"
        assert ResourceStatus.OUT_OF_SERVICE == "OUT_OF_SERVICE"

    def test_all_values(self):
        values = {s.value for s in ResourceStatus}
        assert values == {"AVAILABLE", "DEPLOYED", "EN_ROUTE", "OUT_OF_SERVICE"}
