"""Tests for ogar.tools.resource_tools — LLM tools for querying resources."""

import pytest

from resources.base import ResourceBase, ResourceStatus
from resources.inventory import ResourceInventory
from tools.resource_tools import (
    RESOURCE_TOOLS,
    check_preparedness,
    clear_resource_tool_state,
    get_resource_summary,
    get_resources_by_cluster,
    get_resources_by_type,
    set_resource_tool_state,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_inventory() -> ResourceInventory:
    """Small inventory for tool tests."""
    inv = ResourceInventory(grid_rows=10, grid_cols=10)
    inv.register(ResourceBase(
        resource_id="truck-1", resource_type="firetruck",
        cluster_id="cluster-south", grid_row=9, grid_col=0,
        capacity=500.0, available=500.0, mobile=True,
    ))
    inv.register(ResourceBase(
        resource_id="truck-2", resource_type="firetruck",
        cluster_id="cluster-south", grid_row=9, grid_col=9,
        capacity=500.0, available=500.0, mobile=True,
    ))
    inv.register(ResourceBase(
        resource_id="hospital-1", resource_type="hospital",
        cluster_id="cluster-north", grid_row=1, grid_col=5,
        capacity=50.0, available=42.0, mobile=False,
    ))
    return inv


@pytest.fixture(autouse=True)
def _tool_state():
    """Set and clear resource tool state around each test."""
    inv = _make_inventory()
    set_resource_tool_state(inv)
    yield inv
    clear_resource_tool_state()


# ── Tool list ────────────────────────────────────────────────────────────────

class TestToolList:
    def test_resource_tools_has_four_tools(self):
        assert len(RESOURCE_TOOLS) == 4

    def test_tool_names(self):
        names = {t.name for t in RESOURCE_TOOLS}
        assert names == {
            "get_resource_summary",
            "get_resources_by_cluster",
            "get_resources_by_type",
            "check_preparedness",
        }


# ── get_resource_summary ─────────────────────────────────────────────────────

class TestGetResourceSummary:
    def test_returns_summary(self):
        result = get_resource_summary.invoke({})
        assert result["total_resources"] == 3
        assert "firetruck" in result["by_type"]
        assert "hospital" in result["by_type"]

    def test_no_inventory_returns_error(self):
        clear_resource_tool_state()
        result = get_resource_summary.invoke({})
        assert "error" in result
        assert result["total_resources"] == 0


# ── get_resources_by_cluster ─────────────────────────────────────────────────

class TestGetResourcesByCluster:
    def test_returns_cluster_resources(self):
        result = get_resources_by_cluster.invoke({"cluster_id": "cluster-south"})
        assert len(result) == 2
        assert all(r["cluster_id"] == "cluster-south" for r in result)

    def test_returns_empty_for_unknown_cluster(self):
        result = get_resources_by_cluster.invoke({"cluster_id": "cluster-east"})
        assert result == []

    def test_no_inventory_returns_empty(self):
        clear_resource_tool_state()
        result = get_resources_by_cluster.invoke({"cluster_id": "cluster-south"})
        assert result == []


# ── get_resources_by_type ────────────────────────────────────────────────────

class TestGetResourcesByType:
    def test_returns_typed_resources(self):
        result = get_resources_by_type.invoke({"resource_type": "firetruck"})
        assert len(result) == 2
        assert all(r["resource_type"] == "firetruck" for r in result)

    def test_returns_empty_for_unknown_type(self):
        result = get_resources_by_type.invoke({"resource_type": "airplane"})
        assert result == []


# ── check_preparedness ───────────────────────────────────────────────────────

class TestCheckPreparedness:
    def test_check_specific_cluster(self):
        result = check_preparedness.invoke({"cluster_id": "cluster-south"})
        assert result["cluster_id"] == "cluster-south"
        assert result["total_resources"] == 2
        assert result["available_resources"] == 2
        assert "firetruck" in result["resource_types_present"]
        assert result["total_capacity"] == 1000.0

    def test_check_all_clusters(self):
        result = check_preparedness.invoke({})
        assert result["cluster_id"] == "all"
        assert result["total_resources"] == 3

    def test_check_empty_cluster(self):
        result = check_preparedness.invoke({"cluster_id": "cluster-east"})
        assert result["total_resources"] == 0
        assert len(result["gaps"]) > 0

    def test_no_inventory_returns_error(self):
        clear_resource_tool_state()
        result = check_preparedness.invoke({})
        assert "error" in result

    def test_gaps_detected_when_low_capacity(self, _tool_state):
        inv = _tool_state
        # Consume most capacity
        for r in inv.all_resources():
            r.consume(r.available * 0.9)
        result = check_preparedness.invoke({})
        # Should detect low capacity gap
        assert any("capacity" in g.lower() or "Low" in g for g in result["gaps"])
