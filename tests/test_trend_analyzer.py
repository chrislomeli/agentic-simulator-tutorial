"""Tests for TrendAnalyzer — feature engineering layer for temporal reasoning.

DEFERRED: trend_analyzer.py depends on the removed ``TrendIndicator``
schema. Chunk 3 introduces a simpler ``get_trend()`` accessor on
CellStateManager. Once that lands, this file is either removed or
ported to test the new accessor.
"""

import pytest

pytest.skip("Pending Chunk 3 trend accessor on CellStateManager", allow_module_level=True)

from datetime import datetime, timedelta  # noqa: E402

from world.trend_analyzer import TREND_THRESHOLDS, TrendAnalyzer  # noqa: E402


class TestTrendAnalyzerBuffer:
    """Circular buffer behavior — POC uses fixed 10-reading window."""

    def test_buffer_initially_empty(self):
        analyzer = TrendAnalyzer(buffer_size=10)
        assert len(analyzer._histories) == 0
        assert analyzer.compute_trend("temperature") is None

    def test_buffer_adds_readings(self):
        analyzer = TrendAnalyzer(buffer_size=5)
        now = datetime.now()
        
        for i in range(3):
            analyzer.add_reading("temperature", 20.0 + i, now + timedelta(minutes=i))
        
        history = analyzer._get_or_create_history("temperature")
        assert len(history) == 3

    def test_buffer_evicts_oldest_at_capacity(self):
        analyzer = TrendAnalyzer(buffer_size=3)
        now = datetime.now()
        
        for i in range(5):
            analyzer.add_reading("temperature", 20.0 + i, now + timedelta(minutes=i))
        
        history = analyzer._get_or_create_history("temperature")
        assert len(history) == 3  # Capacity limited


class TestTrendAnalyzerSlope:
    """Linear regression slope calculation — POC uses simple least squares."""

    def test_perfect_linear_trend(self):
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        # Perfect +1°C per minute
        for i in range(5):
            analyzer.add_reading("temperature", 20.0 + i, now + timedelta(minutes=i))
        
        trend = analyzer.compute_trend("temperature")
        assert trend is not None
        assert abs(trend.magnitude - 1.0) < 0.01  # Slope ≈ 1.0°C/min
        assert trend.direction in ("rising", "rising_fast")

    def test_stable_no_trend(self):
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        # Constant temperature
        for i in range(5):
            analyzer.add_reading("temperature", 25.0, now + timedelta(minutes=i))
        
        trend = analyzer.compute_trend("temperature")
        assert trend is not None
        assert abs(trend.magnitude) < 0.01
        assert trend.direction == "stable"

    def test_falling_trend(self):
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        # Humidity dropping (dangerous for wildfire)
        for i in range(5):
            analyzer.add_reading("humidity", 50.0 - i * 2, now + timedelta(minutes=i))
        
        trend = analyzer.compute_trend("humidity")
        assert trend is not None
        assert trend.magnitude < 0  # Negative slope
        assert "falling" in trend.direction


class TestTrendAnalyzerThresholds:
    """Domain-calibrated thresholds — hardcoded in POC, tested for correctness."""

    def test_temperature_rising_fast_threshold(self):
        threshold = TREND_THRESHOLDS["temperature"]["rising_fast"]
        assert threshold == 2.0  # 2°C/min is "fast"

    def test_temperature_rising_threshold(self):
        threshold = TREND_THRESHOLDS["temperature"]["rising"]
        assert threshold == 0.5  # 0.5°C/min is "rising"

    def test_humidity_falling_fast_is_danger(self):
        # For humidity, falling is the danger direction (drying)
        threshold = TREND_THRESHOLDS["humidity"]["falling_fast"]
        assert threshold == -5.0  # -5%/min drying is "fast"


class TestTrendAnalyzerConfidence:
    """Confidence scoring — POC uses simple heuristic (points + variance)."""

    def test_low_confidence_few_points(self):
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        # Only 3 points (minimum)
        for i in range(3):
            analyzer.add_reading("temperature", 20.0 + i, now + timedelta(minutes=i))
        
        trend = analyzer.compute_trend("temperature")
        assert trend is not None
        assert trend.data_points == 3
        assert trend.confidence < 0.7  # Low confidence with few points

    def test_high_confidence_many_points(self):
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        # 10 points (full buffer)
        for i in range(10):
            analyzer.add_reading("temperature", 20.0 + i * 0.5, now + timedelta(minutes=i))
        
        trend = analyzer.compute_trend("temperature")
        assert trend is not None
        assert trend.data_points == 10
        assert trend.confidence > 0.7  # Higher confidence with more points


class TestTrendAnalyzerIntegration:
    """End-to-end: sensor readings → trend indicator for LLM context."""

    def test_typical_wildfire_scenario(self):
        """
        Simulates realistic sensor pattern:
        - Temperature rising from 35°C to 42°C over 10 minutes
        - Humidity dropping from 25% to 12%
        - Wind stable at 8 m/s
        
        Verifies trend directions are correctly identified.
        """
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        # Temperature: rising ~0.7°C/min
        for i in range(10):
            temp = 35.0 + i * 0.7
            analyzer.add_reading("temperature", temp, now + timedelta(minutes=i))
        
        # Humidity: falling ~1.3%/min
        for i in range(10):
            humidity = 25.0 - i * 1.3
            analyzer.add_reading("humidity", humidity, now + timedelta(minutes=i))
        
        # Wind: stable
        for i in range(10):
            analyzer.add_reading("wind_speed", 8.0, now + timedelta(minutes=i))
        
        trends = analyzer.get_all_trends()
        
        # Verify trends detected
        assert "temperature" in trends
        assert trends["temperature"].direction in ("rising", "rising_fast")
        assert trends["temperature"].magnitude > 0.5  # Clearly rising
        
        assert "humidity" in trends
        assert trends["humidity"].magnitude < -1.0  # Clearly falling (below -1.0%/min)
        
        assert "wind_speed" in trends
        assert trends["wind_speed"].direction == "stable"

    def test_insufficient_data_returns_none(self):
        """Edge case: fewer than 3 readings can't compute trend."""
        analyzer = TrendAnalyzer(buffer_size=10)
        now = datetime.now()
        
        analyzer.add_reading("temperature", 20.0, now)
        analyzer.add_reading("temperature", 21.0, now + timedelta(minutes=1))
        
        trend = analyzer.compute_trend("temperature")
        assert trend is None  # Need 3+ points
