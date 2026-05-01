"""Tests for ogar.domains.wildfire.physics."""

import random
import pytest

from domains.wildfire import FireCellState, FireState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FirePhysicsModule
from world.generic_grid import GenericTerrainGrid
from world import StateEvent


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


@pytest.fixture
def physics():
    return FirePhysicsModule(base_probability=0.15, burn_duration_ticks=5)


@pytest.fixture
def environment():
    return FireEnvironmentState(
        temperature_c=38.0,
        humidity_pct=12.0,
        wind_speed_mps=8.0,
        wind_direction_deg=225.0,
    )


@pytest.fixture
def grid(physics):
    return GenericTerrainGrid(rows=5, cols=5, initial_state_factory=physics.initial_cell_state)


class TestFirePhysicsModule:
    def test_is_physics_module_subclass(self):
        from world import PhysicsModule
        assert issubclass(FirePhysicsModule, PhysicsModule)

    def test_initial_cell_state(self, physics):
        state = physics.initial_cell_state(0, 0)
        assert isinstance(state, FireCellState)
        assert state.fire_state == FireState.UNBURNED

    def test_no_events_when_no_fire(self, physics, grid, environment):
        events = physics.tick_physics(grid, environment, tick=0)
        assert events == []

    def test_fire_spreads_to_neighbors(self, physics, grid, environment):
        """With a burning cell, at least one neighbor should ignite over many ticks."""
        # Ignite center cell.
        center = grid.get_cell(2, 2).cell_state
        grid.update_cell_state(2, 2, center.ignited(tick=0, intensity=0.8))

        any_spread = False
        for tick in range(20):
            events = physics.tick_physics(grid, environment, tick=tick)
            for e in events:
                grid.update_cell_state(e.row, e.col, e.new_state)
                if e.new_state.fire_state == FireState.BURNING:
                    any_spread = True

        assert any_spread, "Fire should spread to at least one neighbor over 20 ticks"

    def test_fire_extinguishes_after_burn_duration(self, physics, grid, environment):
        """A cell should extinguish after burn_duration_ticks."""
        center = grid.get_cell(2, 2).cell_state
        grid.update_cell_state(2, 2, center.ignited(tick=0, intensity=0.8))

        extinguished = False
        for tick in range(10):
            events = physics.tick_physics(grid, environment, tick=tick)
            for e in events:
                grid.update_cell_state(e.row, e.col, e.new_state)
                if e.row == 2 and e.col == 2 and e.new_state.fire_state == FireState.BURNED:
                    extinguished = True

        assert extinguished, "Center cell should extinguish after burn_duration_ticks"

    def test_rock_blocks_spread(self, physics, environment):
        """Fire should not spread to rock cells."""
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=physics.initial_cell_state)

        # Make all neighbors rock except (0,0)
        for r in range(3):
            for c in range(3):
                if (r, c) != (1, 1) and (r, c) != (0, 0):
                    grid.update_cell_state(r, c, FireCellState(terrain_type=TerrainType.ROCK, vegetation=0.0))

        # Ignite center
        center = grid.get_cell(1, 1).cell_state
        grid.update_cell_state(1, 1, center.ignited(tick=0, intensity=0.8))

        for tick in range(10):
            events = physics.tick_physics(grid, environment, tick=tick)
            for e in events:
                grid.update_cell_state(e.row, e.col, e.new_state)
                if e.new_state.fire_state == FireState.BURNING:
                    # The only cell that can ignite is (0,0)
                    assert (e.row, e.col) == (0, 0)

    def test_state_events_are_typed(self, physics, grid, environment):
        center = grid.get_cell(2, 2).cell_state
        grid.update_cell_state(2, 2, center.ignited(tick=0, intensity=0.8))

        events = physics.tick_physics(grid, environment, tick=0)
        for event in events:
            assert isinstance(event, StateEvent)
            assert isinstance(event.new_state, FireCellState)

    def test_summarize(self, physics, grid):
        # One burning cell
        center = grid.get_cell(2, 2).cell_state
        grid.update_cell_state(2, 2, center.ignited(tick=0, intensity=0.5))

        summary = physics.summarize(grid)
        assert "burning_cells" in summary
        assert (2, 2) in summary["burning_cells"]
        assert "fire_intensity_map" in summary
        assert "cell_summary" in summary
        assert summary["cell_summary"]["BURNING"] == 1

    def test_humidity_factor(self, physics):
        # Very dry → high factor
        assert physics._compute_humidity_factor(5.0) > 1.0
        # Very humid → low factor
        assert physics._compute_humidity_factor(80.0) < 0.5
