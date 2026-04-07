"""Tests for ogar.world.cell_state — CellState ABC and GenericCell."""

import pytest

from world.cell_state import CellState, GenericCell


# ── Test CellState subclass ──────────────────────────────────────────────────

class DummyCellState(CellState):
    """Minimal concrete CellState for testing."""
    value: float = 0.0
    label: str = "IDLE"

    def summary_label(self) -> str:
        return self.label


class TestCellState:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            CellState()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        state = DummyCellState(value=1.5, label="ACTIVE")
        assert state.value == 1.5
        assert state.summary_label() == "ACTIVE"

    def test_pydantic_serialisation(self):
        state = DummyCellState(value=2.0, label="DONE")
        d = state.model_dump()
        assert d == {"value": 2.0, "label": "DONE"}

    def test_pydantic_deserialisation(self):
        state = DummyCellState.model_validate({"value": 3.0, "label": "X"})
        assert state.value == 3.0
        assert state.summary_label() == "X"

    def test_defaults(self):
        state = DummyCellState()
        assert state.value == 0.0
        assert state.summary_label() == "IDLE"


# ── Test GenericCell ─────────────────────────────────────────────────────────

class TestGenericCell:
    def test_construction(self):
        state = DummyCellState(value=1.0, label="A")
        cell = GenericCell(row=2, col=3, cell_state=state)
        assert cell.row == 2
        assert cell.col == 3
        assert cell.cell_state.value == 1.0
        assert cell.attributes == {}

    def test_with_attributes(self):
        state = DummyCellState()
        cell = GenericCell(row=0, col=0, cell_state=state, attributes={"zone": "north"})
        assert cell.attributes["zone"] == "north"

    def test_to_dict(self):
        state = DummyCellState(value=5.0, label="TEST")
        cell = GenericCell(row=1, col=2, cell_state=state, attributes={"x": 1})
        d = cell.to_dict()
        assert d["row"] == 1
        assert d["col"] == 2
        assert d["layer"] == 0
        assert d["cell_state"] == {"value": 5.0, "label": "TEST"}
        assert d["attributes"] == {"x": 1}

    def test_repr(self):
        state = DummyCellState(label="ACTIVE")
        cell = GenericCell(row=0, col=0, cell_state=state)
        r = repr(cell)
        assert "ACTIVE" in r
        assert "row=0" in r

    def test_cell_state_is_mutable(self):
        """Engine updates cell state by replacing it."""
        state1 = DummyCellState(value=1.0, label="A")
        cell = GenericCell(row=0, col=0, cell_state=state1)
        state2 = DummyCellState(value=2.0, label="B")
        cell.cell_state = state2
        assert cell.cell_state.value == 2.0
        assert cell.cell_state.summary_label() == "B"
