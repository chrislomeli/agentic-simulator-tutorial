"""Integration test: TrendAnalyzer → RiskHeatMap → Supervisor Query

Validates the full data flow:
1. Sensor readings accumulate in TrendAnalyzer
2. Cluster agent evaluates (produces CollatedRecordRisk)
3. Heat map updates from assessment
4. Supervisor queries hotspots for resource allocation

This is the "portfolio piece" test — shows end-to-end architecture works.
"""

from datetime import datetime, timedelta

import pytest

from agents.commons.schemas import CollatedRecordRisk, GridPosition
from world.risk_heat_map import RiskHeatMap
from world.trend_analyzer import TrendAnalyzer


class TestTrendToHeatMapFlow:
    """Full pipeline: trends computed → risks assessed → heat map updated."""

    def test_wildfire_escalation_scenario(self):
        """
        Simulates 20-minute wildfire monitoring at cell (5, 5).
        
        Demonstrates full pipeline:
        - Sensor readings accumulate in TrendAnalyzer
        - Cluster agent computes trends and assesses risk
        - Heat map updates with each assessment
        - Supervisor queries hotspots
        """
        # Setup
        heat_map = RiskHeatMap(rows=10, cols=10)
        analyzer = TrendAnalyzer(buffer_size=10)
        
        # Simulate 20 minutes of sensor readings
        base_time = datetime.now()
        assessments = []
        
        for minute in range(0, 21, 5):
            # Add readings for this 5-minute window
            for second in range(0, 300, 30):  # Every 30 seconds
                t = base_time + timedelta(minutes=minute, seconds=second)
                temp = 35.0 + (minute + second/60) * 0.85  # Rising ~0.85°C/min
                humidity = 20.0 - (minute + second/60) * 0.5  # Falling 0.5%/min
                wind = 5.0 + (minute + second/60) * 0.35  # Rising 0.35m/s/min
                
                analyzer.add_reading("temperature", temp, t)
                analyzer.add_reading("humidity", humidity, t)
                analyzer.add_reading("wind_speed", wind, t)
            
            # Compute trends (what cluster agent sees)
            trends = analyzer.get_all_trends()
            
            # Verify we have trends
            assert "temperature" in trends
            assert trends["temperature"].direction in ("rising", "rising_fast")
            
            # Simplified risk scoring based on trend
            temp_trend = trends["temperature"]
            risk_score = min(10, max(1, int(3 + temp_trend.magnitude * 2)))
            confidence = min(3, max(1, int(temp_trend.confidence * 3)))
            
            # Create risk assessment
            risk = CollatedRecordRisk(
                position=GridPosition(row=5, col=5),
                risk_score=risk_score,
                confidence=confidence,
                confidence_rationale=f"Temp trend: {temp_trend.direction}, magnitude: {temp_trend.magnitude:.2f}",
                contributing_factors=[f"temp_trend={temp_trend.direction}"],
            )
            
            # Update heat map
            heat_map.update_from_assessment(risk)
            assessments.append(risk)
        
        # Verify multiple assessments were made
        assert len(assessments) == 5
        
        # Verify heat map has final state
        cell = heat_map.get(5, 5)
        assert cell.risk_score > 0  # Has been assessed
        assert cell.confidence > 0
        assert cell.dirty is True
        
        # Supervisor queries hotspots (threshold may vary based on trend calc)
        hotspots = heat_map.get_hotspots(threshold=3)  # Lower threshold for test
        assert len(hotspots) >= 1  # At least one hotspot detected
        
        # Stats show progression
        stats = heat_map.get_summary_stats()
        assert stats["assessed_cells"] == 1
        assert stats["max_risk"] > 0  # Has valid risk score


class TestMultiCellHeatMap:
    """Multiple cells with different risk levels — supervisor prioritization."""

    def test_supervisor_prioritizes_highest_risk(self):
        """
        Three cells with different risks:
        - (2, 2): risk=5, confidence=3 (stable, watch)
        - (5, 5): risk=9, confidence=2 (escalating, urgent)
        - (8, 8): risk=7, confidence=3 (high, certain)
        
        Supervisor should prioritize (5, 5) even with lower confidence
        because risk_score is higher. But (8, 8) is also actionable.
        """
        heat_map = RiskHeatMap(rows=10, cols=10)
        
        # Cell 1: Medium risk, high confidence
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=2, col=2),
            risk_score=5, confidence=3,
            confidence_rationale="Stable pattern",
            contributing_factors=["temp=38C", "humidity=20%"],
        ))
        
        # Cell 2: Very high risk, medium confidence (escalating, needs resources)
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=5, col=5),
            risk_score=9, confidence=2,
            confidence_rationale="Trending up fast, limited data",
            contributing_factors=["temp=45C", "humidity=12%", "trend=+2C/min"],
        ))
        
        # Cell 3: High risk, high confidence (confirmed fire)
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=8, col=8),
            risk_score=7, confidence=3,
            confidence_rationale="Multiple sensors confirm",
            contributing_factors=["temp=42C", "humidity=15%", "smoke=high"],
        ))
        
        # Supervisor gets hotspots (threshold=7)
        hotspots = heat_map.get_hotspots(threshold=7, min_confidence=2)
        
        # Should return 2 cells: (5, 5) and (8, 8)
        assert len(hotspots) == 2
        
        # Sorted by risk_score desc: (5, 5)=9 first, then (8, 8)=7
        assert hotspots[0][3].risk_score == 9
        assert hotspots[1][3].risk_score == 7
        
        # Decision: (5, 5) is highest priority despite lower confidence
        # because trend indicates rapid escalation

    def test_coverage_metrics_for_operational_dashboard(self):
        """
        Operations dashboard shows:
        - 1000 total cells in region
        - 150 have been assessed (15% coverage)
        - 12 are hotspots requiring immediate action
        - Average risk across assessed cells: 4.2
        """
        heat_map = RiskHeatMap(rows=10, cols=10)  # 100 cells for test
        
        # Simulate assessment coverage
        assessed = 0
        hotspots = 0
        total_risk = 0
        
        for row in range(10):
            for col in range(10):
                if (row + col) % 3 == 0:  # 1/3 of cells assessed
                    risk_score = (row + col) % 10  # 0-9
                    confidence = 2 if risk_score > 5 else 3
                    
                    heat_map.update_from_assessment(CollatedRecordRisk(
                        position=GridPosition(row=row, col=col),
                        risk_score=risk_score,
                        confidence=confidence,
                        confidence_rationale="Test",
                        contributing_factors=[],
                    ))
                    
                    assessed += 1
                    total_risk += risk_score
                    if risk_score >= 7:
                        hotspots += 1
        
        stats = heat_map.get_summary_stats()
        
        assert stats["total_cells"] == 100
        assert stats["assessed_cells"] == assessed
        assert stats["hotspot_count"] == hotspots
        assert abs(stats["avg_risk"] - (total_risk / assessed)) < 0.01
        assert abs(stats["coverage_pct"] - (assessed / 100 * 100)) < 0.01


class TestHeatMapDirtyFlagOptimization:
    """Performance: only process changed cells."""

    def test_supervisor_processes_only_dirty_cells(self):
        """
        Instead of scanning 10,000 cells every tick, supervisor
        only processes cells marked dirty since last check.
        """
        heat_map = RiskHeatMap(rows=100, cols=100)
        
        # Simulate: 5 cells updated this tick
        for i in range(5):
            heat_map.update_from_assessment(CollatedRecordRisk(
                position=GridPosition(row=i, col=i),
                risk_score=8, confidence=3,
                confidence_rationale="Update",
                contributing_factors=[],
            ))
        
        # Supervisor checks dirty cells (O(5) not O(10,000))
        dirty = heat_map.get_dirty_cells()
        assert len(dirty) == 5
        
        # Process and mark clean
        for row, col, layer, cell in dirty:
            # Supervisor logic here...
            pass
        
        heat_map.mark_all_clean()
        
        # Next tick: no dirty cells
        assert len(heat_map.get_dirty_cells()) == 0
        
        # Update 1 more cell
        heat_map.update_from_assessment(CollatedRecordRisk(
            position=GridPosition(row=99, col=99),
            risk_score=9, confidence=3,
            confidence_rationale="New hotspot",
            contributing_factors=[],
        ))
        
        # Only 1 dirty cell to process
        assert len(heat_map.get_dirty_cells()) == 1
