"""Tests for FirePhysicsModule — spread logic, burn duration, probability factors."""

import random
import pytest

from domains.wildfire import FireCellState, FireState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FirePhysicsModule
from world.generic_grid import GenericTerrainGrid
from world import StateEvent, PhysicsModule


# ── Interface tests ──────────────────────────────────────────────────────────

class TestPhysicsInterface:
    def test_state_event_fields(self):
        state = FireCellState().ignited(tick=0, intensity=0.7)
        e = StateEvent(row=3, col=4, new_state=state)
        assert e.row == 3
        assert e.col == 4
        assert e.new_state.fire_state == FireState.BURNING
        assert e.new_state.fire_intensity == 0.7

    def test_physics_module_is_abstract(self):
        with pytest.raises(TypeError):
            PhysicsModule()  # type: ignore[abstract]

    def test_fire_physics_is_concrete(self):
        # Should not raise
        FirePhysicsModule()


# ── Burn duration / extinguish tests ────────────────────────────────────────

class TestBurnDuration:
    def test_cell_extinguishes_after_burn_duration(self):
        physics = FirePhysicsModule(base_probability=0.0, burn_duration_ticks=3)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState(humidity_pct=90.0, wind_speed_mps=0.0)

        ignited = grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.5)
        grid.update_cell_state(1, 1, ignited)

        events = physics.tick_physics(grid=grid, environment=env, tick=3)
        ext_events = [e for e in events if e.new_state.fire_state == FireState.BURNED]
        assert len(ext_events) == 1
        assert ext_events[0].row == 1
        assert ext_events[0].col == 1

    def test_cell_does_not_extinguish_early(self):
        physics = FirePhysicsModule(base_probability=0.0, burn_duration_ticks=5)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState(humidity_pct=90.0, wind_speed_mps=0.0)

        ignited = grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.5)
        grid.update_cell_state(1, 1, ignited)

        events = physics.tick_physics(grid=grid, environment=env, tick=3)
        ext_events = [e for e in events if e.new_state.fire_state == FireState.BURNED]
        assert len(ext_events) == 0


# ── Humidity factor tests ────────────────────────────────────────────────────

class TestHumidityFactor:
    def test_low_humidity_high_factor(self):
        assert FirePhysicsModule._compute_humidity_factor(5.0) > 1.0

    def test_high_humidity_low_factor(self):
        assert FirePhysicsModule._compute_humidity_factor(80.0) < 1.0

    def test_humidity_factor_range(self):
        f_low = FirePhysicsModule._compute_humidity_factor(0.0)
        f_high = FirePhysicsModule._compute_humidity_factor(100.0)
        assert f_low == 1.5
        assert f_high == pytest.approx(0.2)


# ── Spread probability tests ─────────────────────────────────────────────────

class TestSpreadProbability:
    def test_high_probability_downwind_dry(self):
        """Downwind, dry fuel, high vegetation → fire should spread."""
        physics = FirePhysicsModule(base_probability=0.5)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState(
            wind_direction_deg=225.0, wind_speed_mps=12.0, humidity_pct=5.0
        )
        # Set dry, dense fuel on target cell
        dry_state = FireCellState(fuel_moisture=0.0, vegetation=1.0)
        grid.update_cell_state(0, 2, dry_state)

        ignited = grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.8)
        grid.update_cell_state(1, 1, ignited)

        random.seed(42)
        events = physics.tick_physics(grid=grid, environment=env, tick=1)
        ignitions = [e for e in events if e.new_state.fire_state == FireState.BURNING]
        assert len(ignitions) > 0

    def test_no_spread_to_rock(self):
        physics = FirePhysicsModule(base_probability=1.0)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState(humidity_pct=5.0, wind_speed_mps=10.0)

        # Set all neighbors to rock
        for nr, nc, _nl in grid.neighbors(1, 1):
            rock = FireCellState(terrain_type=TerrainType.ROCK, vegetation=0.0)
            grid.update_cell_state(nr, nc, rock)

        ignited = grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.8)
        grid.update_cell_state(1, 1, ignited)

        events = physics.tick_physics(grid=grid, environment=env, tick=1)
        ignitions = [e for e in events if e.new_state.fire_state == FireState.BURNING]
        assert len(ignitions) == 0

    def test_no_spread_to_water(self):
        physics = FirePhysicsModule(base_probability=1.0)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState()

        for nr, nc, _nl in grid.neighbors(1, 1):
            water = FireCellState(terrain_type=TerrainType.WATER, vegetation=0.0)
            grid.update_cell_state(nr, nc, water)

        ignited = grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.8)
        grid.update_cell_state(1, 1, ignited)

        events = physics.tick_physics(grid=grid, environment=env, tick=1)
        ignitions = [e for e in events if e.new_state.fire_state == FireState.BURNING]
        assert len(ignitions) == 0

    def test_no_double_ignition(self):
        """A cell should not be ignited twice in the same tick."""
        physics = FirePhysicsModule(base_probability=1.0, burn_duration_ticks=10)
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState(humidity_pct=5.0, wind_speed_mps=0.0)

        for pos in [(0, 1), (1, 0)]:
            ignited = grid.get_cell(*pos).cell_state.ignited(tick=0, intensity=0.9)
            grid.update_cell_state(*pos, ignited)

        events = physics.tick_physics(grid=grid, environment=env, tick=1)
        ignited_coords = [(e.row, e.col) for e in events if e.new_state.fire_state == FireState.BURNING]
        assert len(ignited_coords) == len(set(ignited_coords))

    def test_no_events_when_no_fire(self):
        physics = FirePhysicsModule()
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)
        env = FireEnvironmentState()
        events = physics.tick_physics(grid=grid, environment=env, tick=0)
        assert events == []

    def test_probability_capped_at_095(self):
        physics = FirePhysicsModule(base_probability=10.0)
        from_state = FireCellState().ignited(tick=0, intensity=1.0)
        to_state = FireCellState(vegetation=1.0, fuel_moisture=0.0)
        prob = physics._spread_probability(
            1, 1, 0, 0,
            from_state, to_state,
            -0.7, 0.7, 15.0,
            1.5,
        )
        assert prob <= 0.95
