"""Tests for RiskHeatMap — grid-aligned risk state layer.

Coverage:
- Grid initialization with baseline risk=0
- Cell updates from risk assessments
- Hotspot queries for supervisor
- Dirty flag tracking for incremental updates
- Summary statistics

Architecture: In-memory for POC, DB persistence in backlog.
"""

from datetime import datetime

import pytest

from agents.commons.schemas import CollatedRecordRisk, GridPosition
from world.risk_heat_map import RiskHeatMap, CellRiskState, create_risk_heat_map


class TestRiskHeatMapInitialization:
    """Grid setup — 1:1 with terrain, all cells baseline risk=0."""

    def test_initializes_with_correct_dimensions(self):
        heat_map = RiskHeatMap(rows=50, cols=50, layers=1)
        assert heat_map.rows == 50
        assert heat_map.cols == 50
        assert heat_map.layers == 1

    def test_all_cells_baseline_risk_zero(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        for row in range(10):
            for col in range(10):
                cell = heat_map.get(row, col)
                assert cell is not None
                assert cell.risk_score == 0
                assert cell.confidence == 0
                assert cell.assessed_at is None
                assert cell.dirty is False

    def test_factory_creates_matching_grid(self):
        """create_risk_heat_map() ensures 1:1 mapping with terrain."""
        heat_map = create_risk_heat_map(rows=100, cols=100, layers=1)
        assert heat_map.rows == 100
        assert heat_map.cols == 100


class TestRiskHeatMapUpdates:
    """Risk assessment updates — cluster agent writes, supervisor reads."""

    def test_update_from_assessment(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        risk = CollatedRecordRisk(
            position=GridPosition(row=5, col=5, layer=0),
            risk_score=8,
            confidence=3,
            confidence_rationale="High temp + low humidity",
            contributing_factors=["temp=45C", "humidity=10%"],
        )
        
        success = heat_map.update_from_assessment(risk)
        assert success is True
        
        cell = heat_map.get(5, 5)
        assert cell.risk_score == 8
        assert cell.confidence == 3
        assert cell.dirty is True
        assert cell.assessed_at is not None

    def test_update_out_of_bounds_fails_gracefully(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        risk = CollatedRecordRisk(
            position=GridPosition(row=15, col=15, layer=0),  # Outside grid
            risk_score=8,
            confidence=3,
            confidence_rationale="Test",
            contributing_factors=[],
        )
        
        success = heat_map.update_from_assessment(risk)
        assert success is False

    def test_multiple_updates_same_cell(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # First assessment: risk=5
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=3, col=3),
            risk_score=5, confidence=2,
            confidence_rationale="First",
            contributing_factors=[],
        ))
        
        # Second assessment: risk=8 (escalated)
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=3, col=3),
            risk_score=8, confidence=3,
            confidence_rationale="Escalated",
            contributing_factors=["temp rising"],
        ))
        
        cell = heat_map.get(3, 3)
        assert cell.risk_score == 8  # Latest value
        assert cell.confidence == 3


class TestRiskHeatMapHotspots:
    """Supervisor queries — "Where are the fires?"""

    def test_get_hotspots_returns_high_risk_cells(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # Create some hotspots
        for i in range(3):
            heat_map.update_from_assessment(CollatedRecordRisk(
                position=GridPosition(row=i, col=i),
                risk_score=8 + i,  # 8, 9, 10
                confidence=3,
                confidence_rationale="Hotspot",
                contributing_factors=[],
            ))
        
        # Create some low-risk cells
        for i in range(3):
            heat_map.update_from_assessment(CollatedRecordRisk(
                position=GridPosition(row=i+5, col=i+5),
                risk_score=3,  # Below threshold
                confidence=2,
                confidence_rationale="Low",
                contributing_factors=[],
            ))
        
        hotspots = heat_map.get_hotspots(threshold=7, min_confidence=2)
        assert len(hotspots) == 3
        
        # Should be sorted by risk_score desc
        assert hotspots[0][3].risk_score == 10
        assert hotspots[1][3].risk_score == 9
        assert hotspots[2][3].risk_score == 8

    def test_hotspots_respects_confidence_threshold(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # High risk, low confidence
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=1, col=1),
            risk_score=9, confidence=1,  # Low confidence
            confidence_rationale="Unsure",
            contributing_factors=[],
        ))
        
        # Medium risk, high confidence
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=2, col=2),
            risk_score=8, confidence=3,  # High confidence
            confidence_rationale="Sure",
            contributing_factors=[],
        ))
        
        # Only the high-confidence cell should be in hotspots
        hotspots = heat_map.get_hotspots(threshold=7, min_confidence=2)
        assert len(hotspots) == 1
        assert hotspots[0][0] == 2  # row=2


class TestRiskHeatMapDirtyTracking:
    """Incremental updates — CellStateManager marks dirty, supervisor processes."""

    def test_dirty_cells_tracked(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # Update a few cells
        for i in range(3):
            heat_map.update_from_assessment(CollatedRecordRisk(
                position=GridPosition(row=i, col=i),
                risk_score=5, confidence=2,
                confidence_rationale="Test",
                contributing_factors=[],
            ))
        
        dirty = heat_map.get_dirty_cells()
        assert len(dirty) == 3

    def test_mark_all_clean_clears_dirty(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=1, col=1),
            risk_score=5, confidence=2,
            confidence_rationale="Test",
            contributing_factors=[],
        ))
        
        assert len(heat_map.get_dirty_cells()) == 1
        
        heat_map.mark_all_clean()
        
        assert len(heat_map.get_dirty_cells()) == 0
        cell = heat_map.get(1, 1)
        assert cell.dirty is False

    def test_snapshot_marks_clean(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=1, col=1),
            risk_score=5, confidence=2,
            confidence_rationale="Test",
            contributing_factors=[],
        ))
        
        _ = heat_map.snapshot()
        
        assert len(heat_map.get_dirty_cells()) == 0


class TestRiskHeatMapSummaryStats:
    """Dashboard/monitoring — aggregate metrics for operations."""

    def test_summary_with_mixed_cells(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # 3 assessed cells (1 hotspot)
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=0, col=0),
            risk_score=9, confidence=3,
            confidence_rationale="Hotspot",
            contributing_factors=[],
        ))
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=1, col=1),
            risk_score=5, confidence=2,
            confidence_rationale="Medium",
            contributing_factors=[],
        ))
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=2, col=2),
            risk_score=2, confidence=1,
            confidence_rationale="Low",
            contributing_factors=[],
        ))
        
        stats = heat_map.get_summary_stats()
        
        assert stats["total_cells"] == 100  # 10x10
        assert stats["assessed_cells"] == 3
        assert stats["hotspot_count"] == 1
        assert stats["avg_risk"] == (9 + 5 + 2) / 3  # ~5.33
        assert stats["max_risk"] == 9
        assert stats["coverage_pct"] == 3.0

    def test_empty_grid_stats(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        stats = heat_map.get_summary_stats()
        
        assert stats["total_cells"] == 100
        assert stats["assessed_cells"] == 0
        assert stats["hotspot_count"] == 0
        assert stats["avg_risk"] == 0
        assert stats["coverage_pct"] == 0.0


class TestRiskHeatMapReset:
    """Scenario restart — clean slate without rebuilding object."""

    def test_reset_clears_all_cells(self):
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # Add some data
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=1, col=1),
            risk_score=8, confidence=3,
            confidence_rationale="Test",
            contributing_factors=[],
        ))
        
        heat_map.reset()
        
        cell = heat_map.get(1, 1)
        assert cell.risk_score == 0
        assert cell.confidence == 0
        assert cell.assessed_at is None
        assert cell.dirty is False


class TestCellRiskState:
    """Unit tests for individual cell state."""

    def test_is_hotspot_with_high_risk(self):
        cell = CellRiskState(risk_score=8, confidence=3)
        assert cell.is_hotspot(threshold=7) is True

    def test_is_hotspot_below_threshold(self):
        cell = CellRiskState(risk_score=6, confidence=3)
        assert cell.is_hotspot(threshold=7) is False

    def test_is_hotspot_low_confidence(self):
        cell = CellRiskState(risk_score=9, confidence=1)  # Low confidence
        assert cell.is_hotspot(threshold=7, min_confidence=2) is False
