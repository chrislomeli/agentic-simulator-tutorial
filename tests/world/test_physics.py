"""Tests for ogar.world.physics — PhysicsModule ABC and StateEvent."""

import pytest

from world.cell_state import CellState
from world import PhysicsModule, StateEvent


# ── Test fixtures ────────────────────────────────────────────────────────────

class SimpleCellState(CellState):
    """A trivial cell state with one numeric field."""
    level: int = 0

    def summary_label(self) -> str:
        return "HIGH" if self.level > 5 else "LOW"


class TestStateEvent:
    def test_fields(self):
        state = SimpleCellState(level=3)
        event = StateEvent(row=1, col=2, new_state=state)
        assert event.row == 1
        assert event.col == 2
        assert event.new_state.level == 3

    def test_new_state_is_typed(self):
        state = SimpleCellState(level=10)
        event = StateEvent(row=0, col=0, new_state=state)
        assert event.new_state.summary_label() == "HIGH"


class TestPhysicsModuleABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            PhysicsModule()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all_methods(self):
        """A subclass missing any abstract method cannot be instantiated."""

        class IncompletePhysics(PhysicsModule[SimpleCellState]):
            def initial_cell_state(self, row, col, layer=0):
                return SimpleCellState()
            # missing tick_physics and summarize

        with pytest.raises(TypeError):
            IncompletePhysics()  # type: ignore[abstract]
