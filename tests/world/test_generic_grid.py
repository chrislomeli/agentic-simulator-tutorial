"""Tests for ogar.world.generic_grid — GenericTerrainGrid."""

import pytest

from world.cell_state import CellState
from world.generic_grid import GenericTerrainGrid


# ── Test cell state ──────────────────────────────────────────────────────────

class ToyState(CellState):
    """Minimal state for grid tests."""
    tag: str = "EMPTY"
    count: int = 0

    def summary_label(self) -> str:
        return self.tag


def make_toy_state(row: int, col: int, layer: int = 0) -> ToyState:
    """Factory that encodes position into the state for verification."""
    return ToyState(tag="EMPTY", count=row * 100 + col)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestGenericTerrainGrid:
    def test_construction(self):
        grid = GenericTerrainGrid(rows=3, cols=4, initial_state_factory=make_toy_state)
        assert grid.rows == 3
        assert grid.cols == 4

    def test_invalid_dimensions(self):
        with pytest.raises(ValueError):
            GenericTerrainGrid(rows=0, cols=5, initial_state_factory=make_toy_state)
        with pytest.raises(ValueError):
            GenericTerrainGrid(rows=5, cols=-1, initial_state_factory=make_toy_state)

    def test_get_cell(self):
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=make_toy_state)
        cell = grid.get_cell(1, 2)
        assert cell.row == 1
        assert cell.col == 2
        # Factory encoded row*100+col
        assert cell.cell_state.count == 102

    def test_get_cell_out_of_bounds(self):
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=make_toy_state)
        with pytest.raises(IndexError):
            grid.get_cell(3, 0)
        with pytest.raises(IndexError):
            grid.get_cell(-1, 0)

    def test_neighbors_corner(self):
        grid = GenericTerrainGrid(rows=5, cols=5, initial_state_factory=make_toy_state)
        # Top-left corner: only 3 neighbors
        neighbors = grid.neighbors(0, 0)
        assert len(neighbors) == 3
        assert (0, 1, 0) in neighbors
        assert (1, 0, 0) in neighbors
        assert (1, 1, 0) in neighbors

    def test_neighbors_center(self):
        grid = GenericTerrainGrid(rows=5, cols=5, initial_state_factory=make_toy_state)
        # Center cell: 8 neighbors
        neighbors = grid.neighbors(2, 2)
        assert len(neighbors) == 8

    def test_update_cell_state(self):
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=make_toy_state)
        new_state = ToyState(tag="ACTIVE", count=999)
        grid.update_cell_state(1, 1, new_state)
        cell = grid.get_cell(1, 1)
        assert cell.cell_state.tag == "ACTIVE"
        assert cell.cell_state.count == 999

    def test_iter_cells(self):
        grid = GenericTerrainGrid(rows=2, cols=3, initial_state_factory=make_toy_state)
        cells = list(grid.iter_cells())
        assert len(cells) == 6
        # Check row-major order
        assert cells[0].row == 0 and cells[0].col == 0
        assert cells[5].row == 1 and cells[5].col == 2

    def test_cells_where(self):
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=make_toy_state)
        # Mark one cell as ACTIVE
        grid.update_cell_state(1, 1, ToyState(tag="ACTIVE"))
        grid.update_cell_state(2, 0, ToyState(tag="ACTIVE"))

        active = grid.cells_where(lambda c: c.cell_state.tag == "ACTIVE")
        assert len(active) == 2
        assert (1, 1, 0) in active
        assert (2, 0, 0) in active

    def test_snapshot(self):
        grid = GenericTerrainGrid(rows=2, cols=2, initial_state_factory=make_toy_state)
        snap = grid.snapshot()
        assert snap["rows"] == 2
        assert snap["cols"] == 2
        assert snap["layers"] == 1
        assert len(snap["cells"]) == 2
        assert len(snap["cells"][0]) == 2
        # cells[row][col] is a list of layers
        assert len(snap["cells"][0][0]) == 1
        assert snap["cells"][0][0][0]["cell_state"]["tag"] == "EMPTY"

    def test_summary_counts(self):
        grid = GenericTerrainGrid(rows=3, cols=3, initial_state_factory=make_toy_state)
        grid.update_cell_state(0, 0, ToyState(tag="ACTIVE"))
        grid.update_cell_state(1, 1, ToyState(tag="ACTIVE"))
        grid.update_cell_state(2, 2, ToyState(tag="DONE"))

        counts = grid.summary_counts()
        assert counts["ACTIVE"] == 2
        assert counts["DONE"] == 1
        assert counts["EMPTY"] == 6
