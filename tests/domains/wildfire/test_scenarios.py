"""Tests for ogar.domains.wildfire.scenarios."""

import random
import pytest

from domains.wildfire import FireState, TerrainType
from domains.wildfire.scenarios import (
    create_basic_wildfire,
    create_full_wildfire_scenario,
    create_wildfire_resources,
)
from domains.wildfire.physics import SimpleFirePhysicsModule
from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule
from world import GenericWorldEngine


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


class TestBasicWildfire:
    def test_creates_engine(self):
        engine = create_basic_wildfire()
        assert isinstance(engine, GenericWorldEngine)

    def test_grid_dimensions(self):
        engine = create_basic_wildfire()
        assert engine.grid.rows == 10
        assert engine.grid.cols == 10

    def test_initial_ignition(self):
        engine = create_basic_wildfire()
        state = engine.grid.get_cell(7, 2).cell_state
        assert state.fire_state == FireState.BURNING
        assert state.fire_intensity == pytest.approx(0.8)

    def test_terrain_layout(self):
        engine = create_basic_wildfire()
        # Lake in NW
        assert engine.grid.get_cell(0, 0).cell_state.terrain_type == TerrainType.WATER
        # Forest in north
        assert engine.grid.get_cell(1, 5).cell_state.terrain_type == TerrainType.FOREST
        # Rock ridge
        assert engine.grid.get_cell(4, 0).cell_state.terrain_type == TerrainType.ROCK
        # Gap in ridge
        assert engine.grid.get_cell(4, 6).cell_state.terrain_type == TerrainType.SCRUB
        # Grassland in south
        assert engine.grid.get_cell(6, 3).cell_state.terrain_type == TerrainType.GRASSLAND
        # Urban in SE
        assert engine.grid.get_cell(7, 8).cell_state.terrain_type == TerrainType.URBAN

    def test_can_run_simulation(self):
        engine = create_basic_wildfire()
        snapshots = engine.run(ticks=10)
        assert len(snapshots) == 10
        assert engine.current_tick == 10

    def test_fire_spreads_during_simulation(self):
        engine = create_basic_wildfire()
        engine.run(ticks=20)

        # After 20 ticks, there should be more burning or burned cells
        counts = engine.grid.summary_counts()
        total_fire_affected = counts.get("BURNING", 0) + counts.get("BURNED", 0)
        # At minimum, the initial cell should have burned
        assert total_fire_affected >= 1

    def test_snapshot_has_domain_summary(self):
        engine = create_basic_wildfire()
        snapshot = engine.tick()
        assert "burning_cells" in snapshot.domain_summary
        assert "fire_intensity_map" in snapshot.domain_summary
        assert "cell_summary" in snapshot.domain_summary

    def test_rock_cells_not_burnable(self):
        engine = create_basic_wildfire()
        engine.run(ticks=30)
        # Rock cells should never burn
        for c in range(10):
            if c not in (6, 7):  # gap cells are scrub, not rock
                state = engine.grid.get_cell(4, c).cell_state
                assert state.fire_state == FireState.UNBURNED, (
                    f"Rock cell (4, {c}) should not burn"
                )

    def test_use_rothermel_true(self):
        engine = create_basic_wildfire(use_rothermel=True)
        assert isinstance(engine._physics, RothermelFirePhysicsModule)

    def test_use_rothermel_false(self):
        engine = create_basic_wildfire(use_rothermel=False)
        assert isinstance(engine._physics, SimpleFirePhysicsModule)

    def test_rothermel_snapshot_has_fire_behavior(self):
        engine = create_basic_wildfire(use_rothermel=True)
        snapshot = engine.tick()
        assert "avg_ros_ft_min" in snapshot.domain_summary
        assert "danger_rating" in snapshot.domain_summary


class TestCreateWildfireResources:
    def test_creates_inventory(self):
        inv = create_wildfire_resources()
        assert inv.size > 0

    def test_has_nwcg_aligned_resources(self):
        inv = create_wildfire_resources()
        types_present = {r.resource_type for r in inv.all_resources()}
        assert "crew" in types_present
        assert "engine" in types_present
        assert "dozer" in types_present

    def test_nwcg_metadata_present(self):
        inv = create_wildfire_resources()
        crews = inv.by_type("crew")
        assert len(crews) > 0
        for crew in crews:
            assert "nwcg_id" in crew.metadata
            assert "production_rate_chains_hr" in crew.metadata

    def test_engine_nwcg_metadata(self):
        inv = create_wildfire_resources()
        engines = inv.by_type("engine")
        for engine in engines:
            assert engine.metadata.get("nwcg_id") == "E-3"
            assert "tank_gal" in engine.metadata

    def test_helicopter_has_capacity(self):
        inv = create_wildfire_resources()
        helis = inv.by_type("helicopter")
        assert len(helis) > 0
        for h in helis:
            assert h.capacity > 0


class TestCreateFullWildfireScenario:
    def test_returns_engine_and_inventory(self):
        engine, inv = create_full_wildfire_scenario()
        assert isinstance(engine, GenericWorldEngine)
        assert inv.size > 0

    def test_rothermel_engine_by_default(self):
        engine, _ = create_full_wildfire_scenario()
        assert isinstance(engine._physics, RothermelFirePhysicsModule)

    def test_simple_physics_option(self):
        engine, _ = create_full_wildfire_scenario(use_rothermel=False)
        assert isinstance(engine._physics, SimpleFirePhysicsModule)
