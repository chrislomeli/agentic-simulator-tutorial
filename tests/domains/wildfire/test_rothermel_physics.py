"""Tests for ogar.domains.wildfire.rothermel_physics."""

import math
import random

import pytest

from domains.wildfire import FireCellState, FireState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire.fuel_models import FUEL_MODELS
from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule
from world.generic_grid import GenericTerrainGrid
from world.physics import PhysicsModule


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


@pytest.fixture
def physics():
    return RothermelFirePhysicsModule(
        cell_size_ft=200.0,
        time_step_min=5.0,
        burn_duration_ticks=5,
    )


@pytest.fixture
def hot_dry_windy():
    """Hot, dry, windy conditions — high fire danger."""
    return FireEnvironmentState(
        temperature_c=40.0,       # 104°F
        humidity_pct=5.0,
        wind_speed_mps=12.0,      # ~26.8 mph
        wind_direction_deg=225.0,
    )


@pytest.fixture
def cool_wet_calm():
    """Cool, wet, calm conditions — low fire danger."""
    return FireEnvironmentState(
        temperature_c=15.0,       # 59°F
        humidity_pct=55.0,
        wind_speed_mps=1.0,       # ~2.2 mph
        wind_direction_deg=0.0,
    )


@pytest.fixture
def grassland_cell():
    return FireCellState(
        terrain_type=TerrainType.GRASSLAND,
        vegetation=0.8,
        fuel_moisture=0.05,   # very dry
        slope=0.0,
    )


@pytest.fixture
def forest_cell():
    return FireCellState(
        terrain_type=TerrainType.FOREST,
        vegetation=0.9,
        fuel_moisture=0.28,   # near extinction
        slope=0.0,
    )


@pytest.fixture
def grid(physics):
    return GenericTerrainGrid(
        rows=5, cols=5,
        initial_state_factory=physics.initial_cell_state,
    )


class TestPhysicsModuleInterface:
    def test_is_physics_module_subclass(self):
        assert issubclass(RothermelFirePhysicsModule, PhysicsModule)

    def test_initial_cell_state(self, physics):
        state = physics.initial_cell_state(0, 0)
        assert isinstance(state, FireCellState)
        assert state.fire_state == FireState.UNBURNED

    def test_no_events_when_no_fire(self, physics, grid, hot_dry_windy):
        events = physics.tick_physics(grid, hot_dry_windy, tick=0)
        assert events == []


class TestROSComputation:
    def test_ros_grassland_hot_dry_windy(self, physics, hot_dry_windy, grassland_cell):
        """High ROS expected under hot, dry, windy conditions on grassland."""
        fuel_model = FUEL_MODELS[TerrainType.GRASSLAND]
        ros = physics._compute_ros(
            fuel_model, hot_dry_windy, grassland_cell, wind_alignment=1.0
        )
        # Grassland base is 18 ft/min; with strong wind and dry conditions
        # we expect significantly above base.
        assert ros > 18.0, f"Expected ROS > 18, got {ros:.2f}"

    def test_ros_forest_wet_calm(self, physics, cool_wet_calm, forest_cell):
        """Low ROS expected on wet forest with calm wind."""
        fuel_model = FUEL_MODELS[TerrainType.FOREST]
        ros = physics._compute_ros(
            fuel_model, cool_wet_calm, forest_cell, wind_alignment=0.0
        )
        # Forest base is 6 ft/min; with wet fuel and no wind, should be well below base.
        assert ros < 6.0, f"Expected ROS < 6, got {ros:.2f}"

    def test_ros_wind_alignment_effect(self, physics, hot_dry_windy, grassland_cell):
        """Downwind ROS should be greater than cross-wind or backing ROS."""
        fuel_model = FUEL_MODELS[TerrainType.GRASSLAND]
        ros_heading = physics._compute_ros(fuel_model, hot_dry_windy, grassland_cell, wind_alignment=1.0)
        ros_flank = physics._compute_ros(fuel_model, hot_dry_windy, grassland_cell, wind_alignment=0.0)
        ros_back = physics._compute_ros(fuel_model, hot_dry_windy, grassland_cell, wind_alignment=-1.0)
        assert ros_heading > ros_flank
        assert ros_flank >= ros_back

    def test_ros_floor(self, physics, cool_wet_calm, forest_cell):
        """ROS should never fall below 0.1 ft/min (floor)."""
        fuel_model = FUEL_MODELS[TerrainType.FOREST]
        # Extreme wet conditions
        cell = forest_cell.model_copy(update={"fuel_moisture": 1.0, "vegetation": 0.01})
        ros = physics._compute_ros(fuel_model, cool_wet_calm, cell, wind_alignment=0.0)
        assert ros >= 0.1


class TestDerivedMetrics:
    def test_flame_length_formula(self, physics):
        """Known inputs should produce expected flame length."""
        # L = (ROS × heat_content / 500) ^ 0.46
        ros = 10.0
        heat = 8000.0
        expected = (ros * heat / 500.0) ** 0.46
        result = physics._compute_flame_length(ros, heat)
        assert result == pytest.approx(expected, rel=1e-6)

    def test_flame_length_increases_with_ros(self, physics):
        """Higher ROS → longer flame."""
        fl_low = physics._compute_flame_length(5.0, 8000.0)
        fl_high = physics._compute_flame_length(20.0, 8000.0)
        assert fl_high > fl_low

    def test_fireline_intensity_formula(self, physics):
        """Known inputs should produce expected fireline intensity (BTU/ft/s)."""
        ros = 10.0    # ft/min
        heat = 9000.0
        mf = 0.5
        # Formula converts ROS to ft/s before multiplying
        expected = (ros / 60.0) * heat * mf * 0.9
        result = physics._compute_fireline_intensity(ros, heat, mf)
        assert result == pytest.approx(expected, rel=1e-6)

    def test_fireline_intensity_non_negative(self, physics):
        result = physics._compute_fireline_intensity(0.1, 8000.0, 0.0)
        assert result >= 0.0


class TestSpreadProbabilityConversion:
    def test_high_ros_high_probability(self, physics):
        """ROS of 200 ft/min with 200 ft cells and 5 min/tick → prob = 0.95 (clamped)."""
        prob = physics._ros_to_spread_probability(200.0)
        assert prob == pytest.approx(0.95)

    def test_low_ros_low_probability(self, physics):
        """ROS of 2 ft/min: spread_distance = 10 ft; prob = 10/200 = 0.05."""
        prob = physics._ros_to_spread_probability(2.0)
        assert prob == pytest.approx(0.05, abs=1e-6)

    def test_probability_clamped_to_max(self, physics):
        prob = physics._ros_to_spread_probability(10000.0)
        assert prob == pytest.approx(0.95)

    def test_probability_positive(self, physics):
        prob = physics._ros_to_spread_probability(0.1)
        assert prob > 0.0


class TestDangerRating:
    def test_low(self, physics):
        assert physics._danger_rating(0.0) == "Low"
        assert physics._danger_rating(7.9) == "Low"

    def test_moderate(self, physics):
        assert physics._danger_rating(8.0) == "Moderate"
        assert physics._danger_rating(15.9) == "Moderate"

    def test_high(self, physics):
        assert physics._danger_rating(16.0) == "High"
        assert physics._danger_rating(23.9) == "High"

    def test_very_high(self, physics):
        assert physics._danger_rating(24.0) == "Very High"
        assert physics._danger_rating(31.9) == "Very High"

    def test_extreme(self, physics):
        assert physics._danger_rating(32.0) == "Extreme"
        assert physics._danger_rating(100.0) == "Extreme"


class TestGridSpread:
    def test_fire_spreads_on_grid(self, physics, hot_dry_windy):
        """After 20 ticks from a single ignition, fire should have spread."""
        grid = GenericTerrainGrid(
            rows=7, cols=7,
            initial_state_factory=physics.initial_cell_state,
        )
        # Dry grassland — fire-prone
        for r in range(7):
            for c in range(7):
                grid.update_cell_state(r, c, FireCellState(
                    terrain_type=TerrainType.GRASSLAND,
                    vegetation=0.8,
                    fuel_moisture=0.05,
                ))

        # Ignite center cell.
        center = grid.get_cell(3, 3).cell_state.ignited(tick=0, intensity=0.9)
        grid.update_cell_state(3, 3, center)

        total_events = 0
        for tick in range(20):
            events = physics.tick_physics(grid, hot_dry_windy, tick)
            for evt in events:
                grid.update_cell_state(evt.row, evt.col, evt.new_state)
            total_events += len(events)

        counts = grid.summary_counts()
        fire_affected = counts.get("BURNING", 0) + counts.get("BURNED", 0)
        assert fire_affected > 1, f"Fire should have spread; only {fire_affected} cell(s) affected"

    def test_metrics_populated_on_burning_cells(self, physics, hot_dry_windy):
        """After a tick, burning cells should have non-zero ROS/flame/intensity."""
        grid = GenericTerrainGrid(
            rows=5, cols=5,
            initial_state_factory=physics.initial_cell_state,
        )
        for r in range(5):
            for c in range(5):
                grid.update_cell_state(r, c, FireCellState(
                    terrain_type=TerrainType.GRASSLAND,
                    vegetation=0.8,
                    fuel_moisture=0.05,
                ))

        ignited = grid.get_cell(2, 2).cell_state.ignited(
            tick=0, intensity=0.9,
            rate_of_spread_ft_min=12.0,
            flame_length_ft=7.0,
            fireline_intensity_btu_ft_s=300.0,
        )
        grid.update_cell_state(2, 2, ignited)

        # Run one tick — should update metrics on the burning cell.
        events = physics.tick_physics(grid, hot_dry_windy, tick=1)
        for evt in events:
            grid.update_cell_state(evt.row, evt.col, evt.new_state)

        burning_state = grid.get_cell(2, 2).cell_state
        if burning_state.fire_state == FireState.BURNING:
            assert burning_state.rate_of_spread_ft_min > 0.0
            assert burning_state.flame_length_ft > 0.0
            assert burning_state.fireline_intensity_btu_ft_s > 0.0

    def test_extinguished_cells_zero_metrics(self, physics, hot_dry_windy):
        """Cells that burn out should have zero fire behavior metrics."""
        # Use a short burn duration so cell extinguishes quickly.
        fast_physics = RothermelFirePhysicsModule(
            cell_size_ft=200.0, time_step_min=5.0, burn_duration_ticks=2
        )
        grid = GenericTerrainGrid(
            rows=3, cols=3,
            initial_state_factory=fast_physics.initial_cell_state,
        )
        for r in range(3):
            for c in range(3):
                grid.update_cell_state(r, c, FireCellState(
                    terrain_type=TerrainType.GRASSLAND,
                    vegetation=0.8,
                    fuel_moisture=0.05,
                ))

        # Isolate center — surround with rock so fire can't spread.
        for r in range(3):
            for c in range(3):
                if not (r == 1 and c == 1):
                    grid.update_cell_state(r, c, FireCellState(terrain_type=TerrainType.ROCK))

        ignited = grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.9)
        grid.update_cell_state(1, 1, ignited)

        for tick in range(5):
            events = fast_physics.tick_physics(grid, hot_dry_windy, tick)
            for evt in events:
                grid.update_cell_state(evt.row, evt.col, evt.new_state)

        state = grid.get_cell(1, 1).cell_state
        assert state.fire_state == FireState.BURNED
        assert state.rate_of_spread_ft_min == 0.0
        assert state.flame_length_ft == 0.0
        assert state.fireline_intensity_btu_ft_s == 0.0


class TestSummarize:
    def test_summarize_no_fire(self, physics, grid):
        summary = physics.summarize(grid)
        assert "burning_cells" in summary
        assert "avg_ros_ft_min" in summary
        assert "max_ros_ft_min" in summary
        assert "avg_flame_length_ft" in summary
        assert "max_fireline_intensity" in summary
        assert "estimated_acres_hr" in summary
        assert "danger_rating" in summary
        assert summary["avg_ros_ft_min"] == 0.0
        assert summary["danger_rating"] == "Low"

    def test_summarize_includes_fire_behavior(self, physics, hot_dry_windy):
        """After ticks on a burning grid, summarize returns non-zero fire behavior fields."""
        grid = GenericTerrainGrid(
            rows=5, cols=5,
            initial_state_factory=physics.initial_cell_state,
        )
        for r in range(5):
            for c in range(5):
                grid.update_cell_state(r, c, FireCellState(
                    terrain_type=TerrainType.GRASSLAND,
                    vegetation=0.8,
                    fuel_moisture=0.05,
                ))

        ignited = grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=0.9)
        grid.update_cell_state(2, 2, ignited)

        for tick in range(3):
            events = physics.tick_physics(grid, hot_dry_windy, tick)
            for evt in events:
                grid.update_cell_state(evt.row, evt.col, evt.new_state)

        summary = physics.summarize(grid)
        assert summary["max_ros_ft_min"] > 0.0
        assert summary["max_fireline_intensity"] > 0.0
        assert summary["danger_rating"] in (
            "Low", "Moderate", "High", "Very High", "Extreme"
        )
