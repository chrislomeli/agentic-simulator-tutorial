"""Tests for GenericTerrainGrid[FireCellState] — fire-domain grid integration."""

import pytest

from domains.wildfire import FireCellState, FireState, TerrainType
from domains.wildfire import FirePhysicsModule
from world.generic_grid import GenericTerrainGrid


@pytest.fixture
def physics():
    return FirePhysicsModule()


@pytest.fixture
def small_fire_grid(physics) -> GenericTerrainGrid:
    return GenericTerrainGrid(rows=5, cols=5, initial_state_factory=physics.initial_cell_state)


# ── Enum tests ───────────────────────────────────────────────────────────────

class TestEnums:
    def test_terrain_type_values(self):
        assert TerrainType.FOREST == "FOREST"
        assert TerrainType.WATER == "WATER"
        assert len(TerrainType) == 6

    def test_fire_state_values(self):
        assert FireState.UNBURNED == "UNBURNED"
        assert FireState.BURNING == "BURNING"
        assert FireState.BURNED == "BURNED"
        assert len(FireState) == 3


# ── FireCellState tests ──────────────────────────────────────────────────────

class TestFireCellState:
    def test_defaults(self):
        state = FireCellState()
        assert state.terrain_type == TerrainType.GRASSLAND
        assert state.vegetation == 0.5
        assert state.fuel_moisture == 0.3
        assert state.slope == 0.0
        assert state.fire_state == FireState.UNBURNED
        assert state.fire_intensity == 0.0
        assert state.fire_start_tick is None

    def test_custom_terrain(self):
        state = FireCellState(terrain_type=TerrainType.FOREST, vegetation=0.9, fuel_moisture=0.1)
        assert state.terrain_type == TerrainType.FOREST
        assert state.vegetation == 0.9
        assert state.fuel_moisture == 0.1

    def test_is_burnable_default(self):
        assert FireCellState().is_burnable is True

    def test_rock_not_burnable(self):
        assert FireCellState(terrain_type=TerrainType.ROCK, vegetation=0.0).is_burnable is False

    def test_water_not_burnable(self):
        assert FireCellState(terrain_type=TerrainType.WATER, vegetation=0.0).is_burnable is False

    def test_zero_vegetation_not_burnable(self):
        assert FireCellState(vegetation=0.0).is_burnable is False

    def test_burning_cell_not_burnable(self):
        state = FireCellState().ignited(tick=0, intensity=0.5)
        assert state.is_burnable is False

    def test_burned_cell_not_burnable(self):
        state = FireCellState().ignited(tick=0).extinguished()
        assert state.is_burnable is False

    def test_ignited(self):
        state = FireCellState().ignited(tick=3, intensity=0.8)
        assert state.fire_state == FireState.BURNING
        assert state.fire_intensity == 0.8
        assert state.fire_start_tick == 3

    def test_ignited_clamps_intensity(self):
        assert FireCellState().ignited(tick=0, intensity=1.5).fire_intensity == 1.0
        assert FireCellState().ignited(tick=0, intensity=-0.3).fire_intensity == 0.0

    def test_extinguished(self):
        state = FireCellState().ignited(tick=0, intensity=0.7).extinguished()
        assert state.fire_state == FireState.BURNED
        assert state.fire_intensity == 0.0

    def test_to_dict(self):
        state = FireCellState(terrain_type=TerrainType.FOREST, vegetation=0.85)
        d = state.model_dump()
        assert d["terrain_type"] == "FOREST"
        assert d["vegetation"] == 0.85
        assert d["fire_state"] == "UNBURNED"


# ── GenericTerrainGrid[FireCellState] tests ──────────────────────────────────

class TestFireGrid:
    def test_construction(self, small_fire_grid):
        assert small_fire_grid.rows == 5
        assert small_fire_grid.cols == 5

    def test_invalid_dimensions(self, physics):
        with pytest.raises(ValueError):
            GenericTerrainGrid(rows=0, cols=5, initial_state_factory=physics.initial_cell_state)
        with pytest.raises(ValueError):
            GenericTerrainGrid(rows=5, cols=-1, initial_state_factory=physics.initial_cell_state)

    def test_get_cell_valid(self, small_fire_grid):
        from world.cell_state import GenericCell
        cell = small_fire_grid.get_cell(0, 0)
        assert isinstance(cell, GenericCell)
        assert isinstance(cell.cell_state, FireCellState)

    def test_get_cell_out_of_bounds(self, small_fire_grid):
        with pytest.raises(IndexError):
            small_fire_grid.get_cell(5, 0)
        with pytest.raises(IndexError):
            small_fire_grid.get_cell(0, 5)
        with pytest.raises(IndexError):
            small_fire_grid.get_cell(-1, 0)

    def test_neighbors_center(self, small_fire_grid):
        assert len(small_fire_grid.neighbors(2, 2)) == 8

    def test_neighbors_corner(self, small_fire_grid):
        neighbors = small_fire_grid.neighbors(0, 0)
        assert len(neighbors) == 3
        assert (0, 1, 0) in neighbors
        assert (1, 0, 0) in neighbors
        assert (1, 1, 0) in neighbors

    def test_neighbors_edge(self, small_fire_grid):
        assert len(small_fire_grid.neighbors(0, 2)) == 5

    def test_no_burning_cells_initially(self, small_fire_grid):
        burning = small_fire_grid.cells_where(
            lambda c: c.cell_state.fire_state == FireState.BURNING
        )
        assert burning == []

    def test_update_cell_state_to_burning(self, small_fire_grid):
        ignited = small_fire_grid.get_cell(1, 1).cell_state.ignited(tick=0)
        small_fire_grid.update_cell_state(1, 1, ignited)
        ignited2 = small_fire_grid.get_cell(3, 3).cell_state.ignited(tick=0)
        small_fire_grid.update_cell_state(3, 3, ignited2)

        burning = small_fire_grid.cells_where(
            lambda c: c.cell_state.fire_state == FireState.BURNING
        )
        assert len(burning) == 2
        assert (1, 1, 0) in burning
        assert (3, 3, 0) in burning

    def test_fire_intensity_via_cells_where(self, small_fire_grid):
        ignited = small_fire_grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=0.6)
        small_fire_grid.update_cell_state(2, 2, ignited)
        cell = small_fire_grid.get_cell(2, 2)
        assert cell.cell_state.fire_intensity == 0.6

    def test_summary_counts(self, small_fire_grid):
        ignited = small_fire_grid.get_cell(0, 0).cell_state.ignited(tick=0)
        small_fire_grid.update_cell_state(0, 0, ignited)
        burned = small_fire_grid.get_cell(1, 1).cell_state.ignited(tick=0).extinguished()
        small_fire_grid.update_cell_state(1, 1, burned)
        counts = small_fire_grid.summary_counts()
        assert counts["BURNING"] == 1
        assert counts["BURNED"] == 1
        assert counts["UNBURNED"] == 23

    def test_snapshot(self, small_fire_grid):
        snap = small_fire_grid.snapshot()
        assert snap["rows"] == 5
        assert snap["cols"] == 5
        assert len(snap["cells"]) == 5
        assert len(snap["cells"][0]) == 5
        assert snap["cells"][0][0][0]["cell_state"]["terrain_type"] == "GRASSLAND"
