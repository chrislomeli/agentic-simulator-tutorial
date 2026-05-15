"""Tests for the sector_analysis node in agents.logistics."""


from agents.commons.schemas import CellRiskAssessment
from agents.commons.state_types import StatusValue
from agents.logistics.nodes import make_sector_analysis_node
from agents.logistics.state import LogisticsAgentState

# ── Helpers ───────────────────────────────────────────────────────────────────


def _plant_hotspot(engine, row: int, col: int, risk_score: int = 7, confidence: int = 2) -> None:
    """Write a CellRiskAssessment onto a grid cell to simulate a detected hotspot."""
    cell = engine.grid.get_cell(row, col)
    cell.risk_assessment = CellRiskAssessment(
        risk_score=risk_score,
        confidence=confidence,
        confidence_rationale="planted for test",
    )


def _make_state(**overrides) -> LogisticsAgentState:
    base = LogisticsAgentState(workflow_id="test-logistics")
    return base.model_copy(update=overrides) if overrides else base


# ── No hotspots ───────────────────────────────────────────────────────────────


class TestSectorAnalysisNoHotspots:
    def test_no_hotspots_returns_empty_sector_analysis(self, engine):
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert result["sector_analysis"] == []

    def test_no_hotspots_situation_summary_mentions_none_found(self, engine):
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert "No fire hotspots" in result["situation_summary"]

    def test_no_hotspots_status_is_processing(self, engine):
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert result["status"] == StatusValue.PROCESSING

    def test_below_threshold_cell_not_included(self, engine):
        """A cell with risk_score below threshold must not appear as a hotspot."""
        _plant_hotspot(engine, row=2, col=2, risk_score=3)
        node = make_sector_analysis_node(world_engine=engine, risk_threshold=5)
        result = node(_make_state())
        assert result["sector_analysis"] == []


# ── Single hotspot ────────────────────────────────────────────────────────────


class TestSectorAnalysisSingleHotspot:
    def test_hotspot_produces_one_entry(self, engine):
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert len(result["sector_analysis"]) == 1

    def test_hotspot_has_eight_sectors(self, engine):
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        hotspot = result["sector_analysis"][0]
        assert len(hotspot["sectors"]) == 8

    def test_hotspot_epicenter_matches_planted_cell(self, engine):
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        hotspot = result["sector_analysis"][0]
        assert hotspot["epicenter_row"] == 2
        assert hotspot["epicenter_col"] == 2

    def test_hotspot_risk_score_preserved(self, engine):
        _plant_hotspot(engine, row=1, col=1, risk_score=8)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert result["sector_analysis"][0]["risk_score"] == 8

    def test_situation_summary_contains_hotspot_coords(self, engine):
        _plant_hotspot(engine, row=2, col=3, risk_score=6)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert "2" in result["situation_summary"]
        assert "3" in result["situation_summary"]

    def test_all_eight_cardinal_directions_present(self, engine):
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        directions = {s["direction"] for s in result["sector_analysis"][0]["sectors"]}
        assert directions == {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}

    def test_sector_burnable_miles_is_non_negative(self, engine):
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        for sector in result["sector_analysis"][0]["sectors"]:
            assert sector["burnable_miles"] >= 0.0

    def test_corner_hotspot_edge_sectors_are_zero(self, engine):
        """Hotspot in corner — sectors pointing off-grid should have 0 burnable miles."""
        _plant_hotspot(engine, row=0, col=0, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        assert sectors["N"]["burnable_miles"] == 0.0
        assert sectors["NW"]["burnable_miles"] == 0.0
        assert sectors["W"]["burnable_miles"] == 0.0


# ── Multiple hotspots ─────────────────────────────────────────────────────────


class TestSectorAnalysisMultipleHotspots:
    def test_two_hotspots_produce_two_entries(self, engine):
        _plant_hotspot(engine, row=0, col=0, risk_score=6)
        _plant_hotspot(engine, row=4, col=4, risk_score=9)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        assert len(result["sector_analysis"]) == 2

    def test_threshold_filters_correctly(self, engine):
        _plant_hotspot(engine, row=0, col=0, risk_score=4)  # below threshold
        _plant_hotspot(engine, row=4, col=4, risk_score=9)  # above threshold
        node = make_sector_analysis_node(world_engine=engine, risk_threshold=5)
        result = node(_make_state())
        assert len(result["sector_analysis"]) == 1
        assert result["sector_analysis"][0]["risk_score"] == 9


# ── stop_reason tests ─────────────────────────────────────────────────────────


class TestSectorAnalysisStopReason:
    def test_each_sector_has_stop_reason(self, engine):
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        for sector in result["sector_analysis"][0]["sectors"]:
            assert "stop_reason" in sector
            assert sector["stop_reason"] is not None

    def test_corner_hotspot_off_grid_sectors_have_grid_edge(self, engine):
        """Sectors that immediately leave the grid must report grid_edge."""
        _plant_hotspot(engine, row=0, col=0, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        assert sectors["N"]["stop_reason"] == "grid_edge"
        assert sectors["NW"]["stop_reason"] == "grid_edge"
        assert sectors["W"]["stop_reason"] == "grid_edge"

    def test_water_barrier_produces_correct_stop_reason(self, engine):
        """A WATER cell directly north of the hotspot stops the N sector."""
        from world.grid import TerrainType
        engine.grid.get_cell(1, 2).cell_state.terrain_type = TerrainType.WATER
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        assert sectors["N"]["stop_reason"] == "barrier:water"

    def test_urban_barrier_produces_correct_stop_reason(self, engine):
        """An URBAN cell directly east of the hotspot stops the E sector."""
        from world.grid import TerrainType
        engine.grid.get_cell(2, 3).cell_state.terrain_type = TerrainType.URBAN
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        assert sectors["E"]["stop_reason"] == "barrier:urban"

    def test_rock_barrier_produces_correct_stop_reason(self, engine):
        from world.grid import TerrainType
        engine.grid.get_cell(3, 2).cell_state.terrain_type = TerrainType.ROCK
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        assert sectors["S"]["stop_reason"] == "barrier:rock"

    def test_burned_cell_produces_correct_stop_reason(self, engine):
        from world.grid import FireState
        engine.grid.get_cell(2, 3).cell_state.fire_state = FireState.BURNED
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        assert sectors["E"]["stop_reason"] == "burned"

    def test_urban_sector_burnable_miles_excludes_barrier_cell(self, engine):
        """The URBAN cell itself is not burnable — miles stop before it."""
        from world.grid import TerrainType
        engine.grid.get_cell(2, 3).cell_state.terrain_type = TerrainType.URBAN
        _plant_hotspot(engine, row=2, col=2, risk_score=7)
        node = make_sector_analysis_node(world_engine=engine)
        result = node(_make_state())
        sectors = {s["direction"]: s for s in result["sector_analysis"][0]["sectors"]}
        # The barrier is at col 3, one cell east — zero burnable cells before it
        assert sectors["E"]["burnable_miles"] == 0.0
