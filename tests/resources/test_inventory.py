"""Tests for ogar.resources.inventory — ResourceInventory."""

import pytest

from resources.base import ResourceBase, ResourceStatus
from resources.inventory import ResourceInventory


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_resource(**overrides) -> ResourceBase:
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


def _populated_inventory() -> ResourceInventory:
    """Inventory with 3 resources across 2 types and 2 clusters."""
    inv = ResourceInventory(grid_rows=10, grid_cols=10)
    inv.register(_make_resource(
        resource_id="truck-1", resource_type="firetruck",
        cluster_id="cluster-south", grid_row=9, grid_col=0,
    ))
    inv.register(_make_resource(
        resource_id="truck-2", resource_type="firetruck",
        cluster_id="cluster-south", grid_row=9, grid_col=9,
    ))
    inv.register(_make_resource(
        resource_id="hospital-1", resource_type="hospital",
        cluster_id="cluster-north", grid_row=1, grid_col=5,
        capacity=50.0, available=42.0, mobile=False,
    ))
    return inv


# ── Registration ─────────────────────────────────────────────────────────────

class TestRegistration:
    def test_register(self):
        inv = ResourceInventory(grid_rows=10, grid_cols=10)
        r = _make_resource()
        inv.register(r)
        assert inv.size == 1

    def test_register_duplicate_raises(self):
        inv = ResourceInventory(grid_rows=10, grid_cols=10)
        inv.register(_make_resource())
        with pytest.raises(ValueError, match="already registered"):
            inv.register(_make_resource())

    def test_register_out_of_bounds_raises(self):
        inv = ResourceInventory(grid_rows=5, grid_cols=5)
        with pytest.raises(ValueError, match="out of bounds"):
            inv.register(_make_resource(grid_row=10, grid_col=0))

    def test_unregister(self):
        inv = ResourceInventory(grid_rows=10, grid_cols=10)
        inv.register(_make_resource())
        removed = inv.unregister("truck-1")
        assert removed.resource_id == "truck-1"
        assert inv.size == 0

    def test_unregister_missing_raises(self):
        inv = ResourceInventory(grid_rows=10, grid_cols=10)
        with pytest.raises(KeyError):
            inv.unregister("nonexistent")

    def test_unregister_cleans_indices(self):
        inv = _populated_inventory()
        inv.unregister("truck-1")
        # truck-2 still in firetruck type index
        assert len(inv.by_type("firetruck")) == 1
        # cluster-south still has truck-2
        assert len(inv.by_cluster("cluster-south")) == 1


# ── Queries ──────────────────────────────────────────────────────────────────

class TestQueries:
    def test_get_resource(self):
        inv = _populated_inventory()
        r = inv.get_resource("truck-1")
        assert r.resource_id == "truck-1"

    def test_get_resource_missing_raises(self):
        inv = ResourceInventory(grid_rows=10, grid_cols=10)
        with pytest.raises(KeyError):
            inv.get_resource("nonexistent")

    def test_get_resources_at(self):
        inv = _populated_inventory()
        at_9_0 = inv.get_resources_at(9, 0)
        assert len(at_9_0) == 1
        assert at_9_0[0].resource_id == "truck-1"

    def test_get_resources_at_empty(self):
        inv = _populated_inventory()
        assert inv.get_resources_at(0, 0) == []

    def test_all_resources(self):
        inv = _populated_inventory()
        assert len(inv.all_resources()) == 3

    def test_by_type(self):
        inv = _populated_inventory()
        trucks = inv.by_type("firetruck")
        assert len(trucks) == 2
        assert all(r.resource_type == "firetruck" for r in trucks)

    def test_by_type_missing(self):
        inv = _populated_inventory()
        assert inv.by_type("airplane") == []

    def test_by_cluster(self):
        inv = _populated_inventory()
        south = inv.by_cluster("cluster-south")
        assert len(south) == 2

    def test_by_cluster_missing(self):
        inv = _populated_inventory()
        assert inv.by_cluster("cluster-east") == []

    def test_by_status(self):
        inv = _populated_inventory()
        available = inv.by_status(ResourceStatus.AVAILABLE)
        assert len(available) == 3

    def test_by_status_after_deploy(self):
        inv = _populated_inventory()
        inv.deploy("truck-1")
        available = inv.by_status(ResourceStatus.AVAILABLE)
        deployed = inv.by_status(ResourceStatus.DEPLOYED)
        assert len(available) == 2
        assert len(deployed) == 1

    def test_resource_types(self):
        inv = _populated_inventory()
        assert inv.resource_types() == {"firetruck", "hospital"}

    def test_cluster_ids(self):
        inv = _populated_inventory()
        assert inv.cluster_ids() == {"cluster-south", "cluster-north"}

    def test_size(self):
        inv = _populated_inventory()
        assert inv.size == 3


# ── Status transitions ──────────────────────────────────────────────────────

class TestInventoryStatusTransitions:
    def test_deploy(self):
        inv = _populated_inventory()
        inv.deploy("truck-1", row=7, col=2)
        r = inv.get_resource("truck-1")
        assert r.status == ResourceStatus.DEPLOYED
        assert r.grid_row == 7
        assert r.grid_col == 2

    def test_deploy_out_of_bounds_raises(self):
        inv = _populated_inventory()
        with pytest.raises(ValueError, match="out of bounds"):
            inv.deploy("truck-1", row=20, col=0)

    def test_release(self):
        inv = _populated_inventory()
        inv.deploy("truck-1")
        inv.release("truck-1")
        assert inv.get_resource("truck-1").status == ResourceStatus.AVAILABLE


# ── Readiness queries ────────────────────────────────────────────────────────

class TestReadinessQueries:
    def test_readiness_summary_structure(self):
        inv = _populated_inventory()
        summary = inv.readiness_summary()
        assert summary["total_resources"] == 3
        assert "firetruck" in summary["by_type"]
        assert "hospital" in summary["by_type"]
        assert "cluster-south" in summary["by_cluster"]
        assert "cluster-north" in summary["by_cluster"]
        assert "AVAILABLE" in summary["by_status"]

    def test_readiness_summary_empty(self):
        inv = ResourceInventory(grid_rows=10, grid_cols=10)
        summary = inv.readiness_summary()
        assert summary["total_resources"] == 0
        assert summary["by_type"] == {}

    def test_readiness_summary_capacity(self):
        inv = _populated_inventory()
        summary = inv.readiness_summary()
        truck_info = summary["by_type"]["firetruck"]
        assert truck_info["total"] == 2
        assert truck_info["total_capacity"] == 1000.0
        assert truck_info["available_capacity"] == 1000.0

    def test_coverage_by_cluster(self):
        inv = _populated_inventory()
        coverage = inv.coverage_by_cluster()
        assert "firetruck" in coverage["cluster-south"]
        assert "hospital" in coverage["cluster-north"]


# ── Scenario knobs ───────────────────────────────────────────────────────────

class TestScenarioKnobs:
    def test_reduce_resources(self):
        inv = _populated_inventory()
        removed = inv.reduce_resources("firetruck", keep_fraction=0.5)
        assert len(removed) == 1
        assert inv.size == 2

    def test_reduce_resources_invalid_fraction(self):
        inv = _populated_inventory()
        with pytest.raises(ValueError, match="keep_fraction"):
            inv.reduce_resources("firetruck", keep_fraction=1.5)

    def test_disable_resources(self):
        inv = _populated_inventory()
        disabled = inv.disable_resources("firetruck", fraction=1.0)
        assert len(disabled) == 2
        for rid in disabled:
            assert inv.get_resource(rid).status == ResourceStatus.OUT_OF_SERVICE

    def test_disable_resources_invalid_fraction(self):
        inv = _populated_inventory()
        with pytest.raises(ValueError, match="fraction"):
            inv.disable_resources("firetruck", fraction=-0.5)

    def test_reset_all(self):
        inv = _populated_inventory()
        inv.deploy("truck-1")
        inv.get_resource("truck-2").consume(200.0)
        inv.reset_all()
        for r in inv.all_resources():
            assert r.status == ResourceStatus.AVAILABLE
            assert r.available == r.capacity

    def test_repr(self):
        inv = _populated_inventory()
        s = repr(inv)
        assert "resources=3" in s
        assert "10×10" in s
