"""Tests for domains.wildfire.scenarios — create_basic_wildfire."""

from domains.wildfire.scenarios import create_basic_wildfire
from domains.wildfire import TerrainType, FireState
from world import GenericWorldEngine, GenericGroundTruthSnapshot


class TestBasicWildfireScenario:
    def test_returns_generic_engine(self):
        engine = create_basic_wildfire()
        assert isinstance(engine, GenericWorldEngine)

    def test_grid_dimensions(self):
        engine = create_basic_wildfire()
        assert engine.grid.rows == 10
        assert engine.grid.cols == 10

    def test_initial_ignition_at_7_2(self):
        engine = create_basic_wildfire()
        cell = engine.grid.get_cell(7, 2)
        assert cell.cell_state.fire_state == FireState.BURNING
        assert cell.cell_state.fire_intensity == 0.8

    def test_water_in_northwest(self):
        engine = create_basic_wildfire()
        assert engine.grid.get_cell(0, 0).cell_state.terrain_type == TerrainType.WATER
        assert engine.grid.get_cell(1, 0).cell_state.terrain_type == TerrainType.WATER

    def test_forest_in_north(self):
        engine = create_basic_wildfire()
        assert engine.grid.get_cell(2, 5).cell_state.terrain_type == TerrainType.FOREST

    def test_rock_ridge_at_row_4(self):
        engine = create_basic_wildfire()
        assert engine.grid.get_cell(4, 0).cell_state.terrain_type == TerrainType.ROCK
        assert engine.grid.get_cell(4, 6).cell_state.terrain_type == TerrainType.SCRUB
        assert engine.grid.get_cell(4, 7).cell_state.terrain_type == TerrainType.SCRUB

    def test_grassland_in_south(self):
        engine = create_basic_wildfire()
        assert engine.grid.get_cell(6, 3).cell_state.terrain_type == TerrainType.GRASSLAND

    def test_urban_in_southeast(self):
        engine = create_basic_wildfire()
        assert engine.grid.get_cell(7, 8).cell_state.terrain_type == TerrainType.URBAN
        assert engine.grid.get_cell(8, 9).cell_state.terrain_type == TerrainType.URBAN

    def test_weather_conditions(self):
        from domains.wildfire.environment import FireEnvironmentState
        engine = create_basic_wildfire()
        env = engine.environment
        assert isinstance(env, FireEnvironmentState)
        assert env.temperature_c == 38.0
        assert env.humidity_pct == 12.0
        assert env.wind_speed_mps == 8.0
        assert env.wind_direction_deg == 225.0

    def test_engine_can_tick(self):
        engine = create_basic_wildfire()
        snap = engine.tick()
        assert isinstance(snap, GenericGroundTruthSnapshot)
        assert snap.tick == 0
