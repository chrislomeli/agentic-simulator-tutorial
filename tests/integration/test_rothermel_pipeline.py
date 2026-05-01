"""
Integration test: Rothermel physics → fire behavior tools → resource gap analysis.

Tests the end-to-end pipeline:
  1. Create scenario with Rothermel physics
  2. Run 20 ticks
  3. Verify ground truth has fire behavior metrics
  4. Verify fire behavior tools return valid data
  5. Verify resource needs are appropriate for the intensity level
  6. Verify gap analysis identifies shortfalls when resources are degraded
"""

import random

import pytest

from domains.wildfire.scenarios import create_basic_wildfire, create_full_wildfire_scenario
from domains.wildfire.nwcg_resources import suppression_category
from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule
from tools.fire_behavior_tools import (
    clear_fire_behavior_tool_state,
    compare_resources_to_needs,
    get_fire_behavior,
    get_resource_needs,
    set_fire_behavior_tool_state,
)
from tools.resource_tools import clear_resource_tool_state, set_resource_tool_state
from tools.supervisor_tools import clear_supervisor_tool_state


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


@pytest.fixture(autouse=True)
def clean_state():
    yield
    clear_supervisor_tool_state()


@pytest.fixture
def rothermel_engine():
    return create_basic_wildfire(use_rothermel=True)


@pytest.fixture
def full_scenario():
    return create_full_wildfire_scenario(use_rothermel=True)


# ── Step 1-2: Scenario runs with Rothermel physics ───────────────────────────

class TestRothermelScenarioRuns:
    def test_engine_created(self, rothermel_engine):
        from world.generic_engine import GenericWorldEngine
        assert isinstance(rothermel_engine, GenericWorldEngine)
        assert isinstance(rothermel_engine._physics, RothermelFirePhysicsModule)

    def test_fire_spreads_over_20_ticks(self, rothermel_engine):
        rothermel_engine.run(ticks=20)
        counts = rothermel_engine.grid.summary_counts()
        fire_affected = counts.get("BURNING", 0) + counts.get("BURNED", 0)
        assert fire_affected >= 1

    def test_simple_physics_still_works(self):
        """use_rothermel=False should use SimpleFirePhysicsModule without error."""
        engine = create_basic_wildfire(use_rothermel=False)
        engine.run(ticks=5)
        from domains.wildfire.physics import SimpleFirePhysicsModule
        assert isinstance(engine._physics, SimpleFirePhysicsModule)


# ── Step 3: Ground truth has fire behavior metrics ───────────────────────────

class TestGroundTruthFireBehavior:
    def test_snapshot_has_rothermel_fields(self, rothermel_engine):
        """domain_summary should contain Rothermel fire behavior fields."""
        # Run a few ticks so there's actually fire to measure.
        snapshots = rothermel_engine.run(ticks=5)
        last = snapshots[-1]
        ds = last.domain_summary

        # These fields come from RothermelFirePhysicsModule.summarize().
        assert "avg_ros_ft_min" in ds, "avg_ros_ft_min missing from domain_summary"
        assert "max_ros_ft_min" in ds, "max_ros_ft_min missing from domain_summary"
        assert "avg_flame_length_ft" in ds
        assert "max_fireline_intensity" in ds
        assert "estimated_acres_hr" in ds
        assert "danger_rating" in ds

    def test_danger_rating_is_valid_tier(self, rothermel_engine):
        snapshots = rothermel_engine.run(ticks=5)
        valid_tiers = {"Low", "Moderate", "High", "Very High", "Extreme"}
        for snap in snapshots:
            rating = snap.domain_summary.get("danger_rating", "")
            assert rating in valid_tiers, f"Unexpected danger rating: {rating}"

    def test_ros_non_negative(self, rothermel_engine):
        snapshots = rothermel_engine.run(ticks=10)
        for snap in snapshots:
            assert snap.domain_summary.get("avg_ros_ft_min", 0.0) >= 0.0
            assert snap.domain_summary.get("max_ros_ft_min", 0.0) >= 0.0


# ── Step 4: Fire behavior tool returns valid metrics ─────────────────────────

class TestFireBehaviorTool:
    def test_get_fire_behavior_valid_after_ticks(self, rothermel_engine):
        """After running ticks, the tool should return non-error metrics."""
        snapshots = rothermel_engine.run(ticks=10)
        last_ds = snapshots[-1].domain_summary

        set_fire_behavior_tool_state(last_ds)
        result = get_fire_behavior.invoke({})

        assert "error" not in result
        assert result["avg_ros_ft_min"] >= 0.0
        assert result["danger_rating"] in ("Low", "Moderate", "High", "Very High", "Extreme")
        assert result["suppression_category"] in (
            "hand_crew", "engine", "dozer", "aerial_only", "beyond_suppression"
        )


# ── Step 5: Resource needs appropriate for intensity ─────────────────────────

class TestResourceNeedsForIntensity:
    def test_low_intensity_recommends_crews(self):
        """At < 100 BTU/ft/s, crews should be recommended."""
        fb = {"avg_ros_ft_min": 3.0, "max_ros_ft_min": 5.0,
              "avg_flame_length_ft": 2.0, "max_fireline_intensity": 50.0,
              "estimated_acres_hr": 0.1, "danger_rating": "Low"}
        set_fire_behavior_tool_state(fb)
        result = get_resource_needs.invoke({})
        assert result["suppression_difficulty"] == "hand_crew"
        nwcg_ids = {r["nwcg_id"] for r in result["recommended_resources"]}
        assert "C-1" in nwcg_ids

    def test_dozer_intensity_recommends_heavy_equipment(self):
        """At 500–1000 BTU/ft/s, dozers should be recommended."""
        fb = {"avg_ros_ft_min": 15.0, "max_ros_ft_min": 20.0,
              "avg_flame_length_ft": 10.0, "max_fireline_intensity": 700.0,
              "estimated_acres_hr": 5.0, "danger_rating": "High"}
        set_fire_behavior_tool_state(fb)
        result = get_resource_needs.invoke({})
        assert result["suppression_difficulty"] == "dozer"
        nwcg_ids = {r["nwcg_id"] for r in result["recommended_resources"]}
        assert "D-1" in nwcg_ids


# ── Step 6: Gap analysis detects shortfalls ───────────────────────────────────

class TestGapAnalysis:
    def test_adequate_with_full_scenario(self, full_scenario):
        """Full wildfire scenario has crews, engines, dozers — may be adequate at low intensity."""
        engine, inventory = full_scenario
        snapshots = engine.run(ticks=5)
        last_ds = snapshots[-1].domain_summary

        set_fire_behavior_tool_state(last_ds)
        set_resource_tool_state(inventory)

        result = compare_resources_to_needs.invoke({})
        assert "adequate" in result
        assert "gaps" in result
        assert "available" in result
        assert "needed" in result

    def test_gap_identified_with_degraded_resources(self):
        """When no inventory is set, should report gaps for any suppression level."""
        fb = {"avg_ros_ft_min": 25.0, "max_ros_ft_min": 35.0,
              "avg_flame_length_ft": 18.0, "max_fireline_intensity": 1200.0,
              "estimated_acres_hr": 20.0, "danger_rating": "Very High"}
        set_fire_behavior_tool_state(fb)
        # No inventory — compare should report insufficient resources.
        result = compare_resources_to_needs.invoke({})
        assert result["adequate"] is False
        assert len(result["gaps"]) > 0

    def test_gap_analysis_has_correct_fields(self):
        set_fire_behavior_tool_state({
            "max_fireline_intensity": 200.0,
            "avg_ros_ft_min": 8.0,
            "max_ros_ft_min": 12.0,
            "avg_flame_length_ft": 6.0,
            "estimated_acres_hr": 1.5,
            "danger_rating": "Moderate",
        })
        result = compare_resources_to_needs.invoke({})
        for field in ("adequate", "suppression_difficulty", "available", "needed", "gaps", "surplus"):
            assert field in result, f"Missing field: {field}"
