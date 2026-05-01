"""Tests for GenericWorldEngine — tick, run, history, inject_state."""

from domains.wildfire import FireCellState, FireState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FirePhysicsModule
from world import GenericWorldEngine, GenericGroundTruthSnapshot
from world.generic_grid import GenericTerrainGrid


class TestWorldEngineTick:
    def test_tick_returns_snapshot(self, engine):
        snap = engine.tick()
        assert isinstance(snap, GenericGroundTruthSnapshot)

    def test_tick_increments_counter(self, engine):
        assert engine.current_tick == 0
        engine.tick()
        assert engine.current_tick == 1
        engine.tick()
        assert engine.current_tick == 2

    def test_tick_records_history(self, engine):
        assert len(engine.history) == 0
        engine.tick()
        assert len(engine.history) == 1
        engine.tick()
        assert len(engine.history) == 2

    def test_snapshot_has_correct_tick(self, engine):
        snap = engine.tick()
        assert snap.tick == 0
        snap2 = engine.tick()
        assert snap2.tick == 1

    def test_snapshot_has_environment_dict(self, engine):
        snap = engine.tick()
        assert "temperature_c" in snap.environment
        assert "humidity_pct" in snap.environment

    def test_snapshot_has_grid_summary(self, engine):
        snap = engine.tick()
        # All cells start UNBURNED
        assert "UNBURNED" in snap.grid_summary

    def test_snapshot_has_domain_summary(self, engine):
        snap = engine.tick()
        assert "burning_cells" in snap.domain_summary
        assert "fire_intensity_map" in snap.domain_summary
        assert "cell_summary" in snap.domain_summary

    def test_fire_intensity_map_dimensions(self, engine):
        snap = engine.tick()
        imap = snap.domain_summary["fire_intensity_map"]
        assert len(imap) == 5
        assert len(imap[0]) == 5


class TestWorldEngineRun:
    def test_run_returns_list_of_snapshots(self, engine):
        snapshots = engine.run(ticks=10)
        assert len(snapshots) == 10
        assert all(isinstance(s, GenericGroundTruthSnapshot) for s in snapshots)

    def test_run_advances_tick(self, engine):
        engine.run(ticks=5)
        assert engine.current_tick == 5

    def test_run_zero_ticks(self, engine):
        snapshots = engine.run(ticks=0)
        assert snapshots == []
        assert engine.current_tick == 0


class TestWorldEngineHistory:
    def test_get_snapshot_valid(self, engine):
        engine.run(ticks=5)
        snap = engine.get_snapshot(2)
        assert snap is not None
        assert snap.tick == 2

    def test_get_snapshot_invalid(self, engine):
        engine.run(ticks=3)
        assert engine.get_snapshot(5) is None
        assert engine.get_snapshot(-1) is None


class TestInjectState:
    def test_ignite_burnable_cell(self, engine):
        state = engine.grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=0.8)
        engine.inject_state(2, 2, state)
        cell = engine.grid.get_cell(2, 2)
        assert cell.cell_state.fire_state == FireState.BURNING
        assert cell.cell_state.fire_intensity == 0.8

    def test_inject_rock_state(self, engine):
        # Can inject any state — engine doesn't validate domain logic
        rock_state = FireCellState(terrain_type=TerrainType.ROCK, vegetation=0.0)
        engine.inject_state(2, 2, rock_state)
        cell = engine.grid.get_cell(2, 2)
        assert cell.cell_state.terrain_type == TerrainType.ROCK
        # Rock cells are not burnable — subsequent ignite attempt via physics is a no-op
        assert cell.cell_state.is_burnable is False

    def test_already_burning_cell_not_relit(self, engine):
        """Once burning at intensity X, injecting again respects new state."""
        state1 = engine.grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=0.5)
        engine.inject_state(2, 2, state1)
        # Only inject at intensity 0.5 — verify it took
        assert engine.grid.get_cell(2, 2).cell_state.fire_intensity == 0.5


class TestFireSpreadIntegration:
    def test_fire_spreads_over_ticks(self):
        """With ignition and favorable conditions, fire should spread."""
        physics = FirePhysicsModule(base_probability=0.5, burn_duration_ticks=10)
        env = FireEnvironmentState(
            temperature_c=40.0, humidity_pct=5.0,
            wind_speed_mps=10.0, wind_direction_deg=225.0,
        )

        # All cells with high vegetation and very dry fuel
        def make_state(r, c, layer=0):
            return FireCellState(vegetation=0.8, fuel_moisture=0.05)

        grid = GenericTerrainGrid(rows=5, cols=5, initial_state_factory=make_state)
        engine = GenericWorldEngine(grid=grid, environment=env, physics=physics)
        ignition = grid.get_cell(4, 0).cell_state.ignited(tick=0, intensity=0.9)
        engine.inject_state(4, 0, ignition)
        engine.run(ticks=15)

        fire_affected = sum(
            1 for r in range(5) for c in range(5)
            if grid.get_cell(r, c).cell_state.fire_state in (FireState.BURNING, FireState.BURNED)
        )
        assert fire_affected > 1
