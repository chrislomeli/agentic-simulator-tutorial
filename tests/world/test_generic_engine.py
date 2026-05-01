"""Tests for ogar.world.generic_engine — GenericWorldEngine."""

import pytest
from typing import Any, Dict, List

from world.cell_state import CellState
from world import EnvironmentState
from world import GenericGroundTruthSnapshot, GenericWorldEngine
from world.generic_grid import GenericTerrainGrid
from world import PhysicsModule, StateEvent


# ── Toy domain for testing the engine ────────────────────────────────────────
# A trivial "heat" domain: cells have a temperature, the physics module
# increments temperature on "hot" cells each tick.

class HeatCellState(CellState):
    """Toy cell state: tracks temperature."""
    temperature: float = 0.0

    def summary_label(self) -> str:
        if self.temperature >= 100:
            return "HOT"
        elif self.temperature > 0:
            return "WARM"
        return "COLD"


class HeatEnvironment(EnvironmentState):
    """Toy environment: ambient temperature that drifts up each tick."""
    ambient_temp: float = 20.0

    def tick(self) -> None:
        self.ambient_temp += 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {"ambient_temp": self.ambient_temp}


class HeatPhysics(PhysicsModule[HeatCellState]):
    """
    Toy physics: each tick, any cell with temperature > 0 heats its
    right neighbor by 10 degrees.  Simple enough to predict in tests.
    """

    def initial_cell_state(self, row: int, col: int, layer: int = 0) -> HeatCellState:
        return HeatCellState(temperature=0.0)

    def tick_physics(
        self,
        grid: GenericTerrainGrid[HeatCellState],
        environment: HeatEnvironment,
        tick: int,
    ) -> List[StateEvent[HeatCellState]]:
        events = []
        for cell in grid.iter_cells():
            if cell.cell_state.temperature > 0:
                # Heat the cell to the right
                nc = cell.col + 1
                if nc < grid.cols:
                    neighbor = grid.get_cell(cell.row, nc)
                    if neighbor.cell_state.temperature == 0:
                        events.append(StateEvent(
                            row=cell.row,
                            col=nc,
                            new_state=HeatCellState(temperature=10.0),
                        ))
        return events

    def summarize(self, grid: GenericTerrainGrid[HeatCellState]) -> Dict[str, Any]:
        hot = 0
        warm = 0
        for cell in grid.iter_cells():
            if cell.cell_state.temperature >= 100:
                hot += 1
            elif cell.cell_state.temperature > 0:
                warm += 1
        return {"hot_cells": hot, "warm_cells": warm}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def heat_physics():
    return HeatPhysics()


@pytest.fixture
def heat_environment():
    return HeatEnvironment(ambient_temp=20.0)


@pytest.fixture
def heat_grid(heat_physics):
    return GenericTerrainGrid(rows=3, cols=5, initial_state_factory=heat_physics.initial_cell_state)


@pytest.fixture
def heat_engine(heat_grid, heat_environment, heat_physics):
    return GenericWorldEngine(
        grid=heat_grid,
        environment=heat_environment,
        physics=heat_physics,
    )


# ── Tests ────────────────────────────────────────────────────────────────────

class TestGenericWorldEngine:
    def test_initial_state(self, heat_engine):
        assert heat_engine.current_tick == 0
        assert len(heat_engine.history) == 0

    def test_tick_advances_counter(self, heat_engine):
        heat_engine.tick()
        assert heat_engine.current_tick == 1
        heat_engine.tick()
        assert heat_engine.current_tick == 2

    def test_tick_evolves_environment(self, heat_engine):
        heat_engine.tick()
        # Environment started at 20, increments by 1 each tick
        assert heat_engine.environment.ambient_temp == 21.0

    def test_tick_returns_snapshot(self, heat_engine):
        snapshot = heat_engine.tick()
        assert isinstance(snapshot, GenericGroundTruthSnapshot)
        assert snapshot.tick == 0
        assert "ambient_temp" in snapshot.environment

    def test_tick_records_history(self, heat_engine):
        heat_engine.tick()
        heat_engine.tick()
        assert len(heat_engine.history) == 2
        assert heat_engine.history[0].tick == 0
        assert heat_engine.history[1].tick == 1

    def test_get_snapshot(self, heat_engine):
        heat_engine.tick()
        assert heat_engine.get_snapshot(0) is not None
        assert heat_engine.get_snapshot(1) is None
        assert heat_engine.get_snapshot(-1) is None

    def test_run(self, heat_engine):
        snapshots = heat_engine.run(ticks=5)
        assert len(snapshots) == 5
        assert heat_engine.current_tick == 5
        assert len(heat_engine.history) == 5

    def test_inject_state(self, heat_engine):
        hot_state = HeatCellState(temperature=50.0)
        heat_engine.inject_state(1, 2, hot_state)
        cell = heat_engine.grid.get_cell(1, 2)
        assert cell.cell_state.temperature == 50.0

    def test_physics_produces_state_events(self, heat_engine):
        """Inject a hot cell, then tick — its right neighbor should heat up."""
        heat_engine.inject_state(1, 0, HeatCellState(temperature=50.0))

        snapshot = heat_engine.tick()
        # Physics should have heated cell (1,1)
        cell_1_1 = heat_engine.grid.get_cell(1, 1)
        assert cell_1_1.cell_state.temperature == 10.0

        # Snapshot should record the event
        assert len(snapshot.state_events) == 1
        assert snapshot.state_events[0]["row"] == 1
        assert snapshot.state_events[0]["col"] == 1

    def test_physics_chain_propagation(self, heat_engine):
        """Heat should propagate rightward one cell per tick."""
        heat_engine.inject_state(1, 0, HeatCellState(temperature=50.0))

        # Tick 1: cell (1,1) heats up
        heat_engine.tick()
        assert heat_engine.grid.get_cell(1, 1).cell_state.temperature == 10.0
        assert heat_engine.grid.get_cell(1, 2).cell_state.temperature == 0.0

        # Tick 2: cell (1,2) heats up (from (1,1) which is now warm)
        heat_engine.tick()
        assert heat_engine.grid.get_cell(1, 2).cell_state.temperature == 10.0

    def test_domain_summary_in_snapshot(self, heat_engine):
        heat_engine.inject_state(0, 0, HeatCellState(temperature=50.0))
        snapshot = heat_engine.tick()
        assert "warm_cells" in snapshot.domain_summary
        # Cell (0,0) is warm (50 > 0 but < 100)
        assert snapshot.domain_summary["warm_cells"] >= 1

    def test_grid_summary_in_snapshot(self, heat_engine):
        heat_engine.inject_state(0, 0, HeatCellState(temperature=50.0))
        snapshot = heat_engine.tick()
        assert "WARM" in snapshot.grid_summary
        assert "COLD" in snapshot.grid_summary

    def test_no_events_when_grid_is_cold(self, heat_engine):
        """If nothing is hot, physics produces no events."""
        snapshot = heat_engine.tick()
        assert len(snapshot.state_events) == 0


class TestGenericGroundTruthSnapshot:
    def test_fields(self):
        snap = GenericGroundTruthSnapshot(
            tick=5,
            environment={"temp": 30},
            state_events=[{"row": 1, "col": 2, "new_state": {}}],
            domain_summary={"hot": 3},
            grid_summary={"HOT": 3, "COLD": 7},
        )
        assert snap.tick == 5
        assert snap.environment["temp"] == 30
        assert len(snap.state_events) == 1
        assert snap.domain_summary["hot"] == 3
        assert snap.grid_summary["HOT"] == 3
