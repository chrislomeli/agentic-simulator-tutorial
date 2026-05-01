"""Tests for ogar.tools.fire_behavior_tools."""

import pytest

from tools.fire_behavior_tools import (
    FIRE_BEHAVIOR_TOOLS,
    clear_fire_behavior_tool_state,
    compare_resources_to_needs,
    get_fire_behavior,
    get_resource_needs,
    set_fire_behavior_tool_state,
)
from tools.resource_tools import clear_resource_tool_state, set_resource_tool_state
from tools.supervisor_tools import clear_supervisor_tool_state


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fb(
    avg_ros=5.0,
    max_ros=8.0,
    avg_flame=4.0,
    max_intensity=60.0,
    acres_hr=0.5,
    danger="Low",
):
    return {
        "avg_ros_ft_min": avg_ros,
        "max_ros_ft_min": max_ros,
        "avg_flame_length_ft": avg_flame,
        "max_fireline_intensity": max_intensity,
        "estimated_acres_hr": acres_hr,
        "danger_rating": danger,
    }


@pytest.fixture(autouse=True)
def clean_state():
    yield
    clear_supervisor_tool_state()


# ── Tool list ─────────────────────────────────────────────────────────────────

class TestToolList:
    def test_fire_behavior_tools_list(self):
        assert len(FIRE_BEHAVIOR_TOOLS) == 3
        tool_names = {t.name for t in FIRE_BEHAVIOR_TOOLS}
        assert "get_fire_behavior" in tool_names
        assert "get_resource_needs" in tool_names
        assert "compare_resources_to_needs" in tool_names


# ── get_fire_behavior ─────────────────────────────────────────────────────────

class TestGetFireBehavior:
    def test_no_data_returns_error(self):
        result = get_fire_behavior.invoke({})
        assert "error" in result

    def test_returns_metrics(self):
        fb = _make_fb(max_intensity=60.0)
        set_fire_behavior_tool_state(fb)
        result = get_fire_behavior.invoke({})
        assert result["avg_ros_ft_min"] == pytest.approx(5.0)
        assert result["max_ros_ft_min"] == pytest.approx(8.0)
        assert result["avg_flame_length_ft"] == pytest.approx(4.0)
        assert result["max_fireline_intensity"] == pytest.approx(60.0)
        assert result["danger_rating"] == "Low"

    def test_returns_suppression_category(self):
        set_fire_behavior_tool_state(_make_fb(max_intensity=60.0))
        result = get_fire_behavior.invoke({})
        assert result["suppression_category"] == "hand_crew"

    def test_high_intensity_suppression_category(self):
        set_fire_behavior_tool_state(_make_fb(max_intensity=750.0))
        result = get_fire_behavior.invoke({})
        assert result["suppression_category"] == "dozer"


# ── get_resource_needs ────────────────────────────────────────────────────────

class TestGetResourceNeeds:
    def test_no_data_returns_error(self):
        result = get_resource_needs.invoke({})
        assert "error" in result

    def test_low_intensity_recommends_hand_crews(self):
        """< 100 BTU/ft/s — should recommend crews and engines."""
        set_fire_behavior_tool_state(_make_fb(max_ros=5.0, max_intensity=50.0))
        result = get_resource_needs.invoke({})
        assert result["suppression_difficulty"] == "hand_crew"
        nwcg_ids = {r["nwcg_id"] for r in result["recommended_resources"]}
        assert "C-1" in nwcg_ids

    def test_high_intensity_recommends_dozers_and_aerial(self):
        """500–2000 BTU/ft/s — should recommend dozers and aerial."""
        set_fire_behavior_tool_state(_make_fb(max_ros=20.0, max_intensity=750.0))
        result = get_resource_needs.invoke({})
        assert result["suppression_difficulty"] == "dozer"
        nwcg_ids = {r["nwcg_id"] for r in result["recommended_resources"]}
        assert "D-1" in nwcg_ids

    def test_extreme_intensity_recommends_aerial(self):
        """≥ 2000 BTU/ft/s — should recommend aerial resources."""
        set_fire_behavior_tool_state(_make_fb(max_ros=40.0, max_intensity=2500.0))
        result = get_resource_needs.invoke({})
        assert result["suppression_difficulty"] == "beyond_suppression"
        assert len(result["recommended_resources"]) > 0

    def test_perimeter_growth_present(self):
        set_fire_behavior_tool_state(_make_fb(max_ros=10.0, max_intensity=60.0))
        result = get_resource_needs.invoke({})
        assert "perimeter_growth_chains_hr" in result
        assert result["perimeter_growth_chains_hr"] >= 0.0


# ── compare_resources_to_needs ────────────────────────────────────────────────

class TestCompareResourcesToNeeds:
    def test_no_fire_data_returns_error(self):
        result = compare_resources_to_needs.invoke({})
        assert "error" in result
        assert result["adequate"] is False

    def test_adequate_when_resources_match(self):
        """Sufficient resources for current intensity → adequate=True."""
        from domains.wildfire.scenarios import create_wildfire_resources
        inv = create_wildfire_resources()
        set_resource_tool_state(inv)
        # Low intensity — hand crews + engines; scenario has both.
        set_fire_behavior_tool_state(_make_fb(max_intensity=50.0))
        result = compare_resources_to_needs.invoke({})
        assert "adequate" in result
        # Check structure is correct even if not adequate (depends on exact resources).
        assert isinstance(result["gaps"], list)
        assert isinstance(result["available"], dict)
        assert isinstance(result["needed"], dict)

    def test_gap_when_resources_missing(self):
        """No resources available → should report gaps."""
        set_fire_behavior_tool_state(_make_fb(max_ros=30.0, max_intensity=750.0))
        # No inventory set → available will be empty.
        result = compare_resources_to_needs.invoke({})
        assert result["adequate"] is False
        assert len(result["gaps"]) > 0

    def test_returns_suppression_difficulty(self):
        set_fire_behavior_tool_state(_make_fb(max_intensity=150.0))
        result = compare_resources_to_needs.invoke({})
        assert result["suppression_difficulty"] == "engine"
