"""TrendAnalyzer — computes trend indicators from sensor reading history.

POC v1 Design:
- Linear regression on circular buffer (10 readings)
- Domain-calibrated thresholds for wildfire behavior
- Hardcoded configs (configurable via YAML in v2)

ARCHITECTURAL SHORTCUTS (documented for portfolio):
1. Linear regression only (no Kalman filter for noise reduction)
2. Single 5-min window (no multi-timescale: 1-min urgent, 1-hour pattern)
3. Hardcoded thresholds (should be configurable per metric type)

BACKLOG:
- Kalman filter for noisy sensor data
- Configurable thresholds via YAML/config
- Multi-timescale trends (1-min, 5-min, 30-min, 1-hour)
- Persistence: store trend_indicators in DB for historical analysis
"""

from __future__ import annotations

import logging
import statistics
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from agents.commons.schemas import TrendIndicator

logger = logging.getLogger(__name__)

# POC v1: Hardcoded thresholds calibrated for wildfire behavior
# BACKLOG: Make configurable per metric type via YAML
TREND_THRESHOLDS: dict[str, dict[str, float]] = {
    "temperature": {
        "rising_fast": 2.0,      # °C per minute
        "rising": 0.5,         # °C per minute
        "falling_fast": -2.0,  # °C per minute
        "falling": -0.5,       # °C per minute
    },
    "humidity": {
        # For humidity, FALLING is dangerous (drying out)
        "falling_fast": -5.0,  # % per minute
        "falling": -2.0,       # % per minute
        "rising_fast": 5.0,    # % per minute
        "rising": 2.0,         # % per minute
    },
    "wind_speed": {
        "rising_fast": 3.0,    # m/s per minute
        "rising": 1.0,         # m/s per minute
        "falling_fast": -3.0,  # m/s per minute
        "falling": -1.0,       # m/s per minute
    },
}

# Direction mapping based on whether rising or falling is the "danger" direction
DANGER_DIRECTION: dict[str, str] = {
    "temperature": "rising",  # Higher temp = more dangerous
    "humidity": "falling",    # Lower humidity = more dangerous (drying)
    "wind_speed": "rising",   # Higher wind = more dangerous
}

TrendDirection = Literal["rising_fast", "rising", "stable", "falling", "falling_fast"]


@dataclass
class ReadingPoint:
    """A single sensor reading with timestamp."""
    value: float
    timestamp: datetime


class MetricHistory:
    """Circular buffer for a single metric's readings.
    
    POC v1: Fixed 10-reading buffer (~5 min window at 30s tick)
    BACKLOG: Configurable buffer sizes per metric type
    """
    
    def __init__(self, max_size: int = 10) -> None:
        self._buffer: deque[ReadingPoint] = deque(maxlen=max_size)
        self._max_size = max_size
    
    def add(self, value: float, timestamp: datetime | None = None) -> None:
        """Add a new reading, evicting oldest if at capacity."""
        if timestamp is None:
            timestamp = datetime.now()
        self._buffer.append(ReadingPoint(value, timestamp))
    
    def get_readings(self, min_points: int = 3) -> list[ReadingPoint] | None:
        """Get readings if we have enough for trend calculation."""
        if len(self._buffer) < min_points:
            return None
        return list(self._buffer)
    
    def __len__(self) -> int:
        return len(self._buffer)


class TrendAnalyzer:
    """Analyzes metric history to produce trend indicators.
    
    This is the feature engineering layer between raw sensor data
    and LLM evaluation. Converts noisy time series into interpretable
    trend categories with confidence scores.
    """
    
    def __init__(self, buffer_size: int = 10) -> None:
        self._buffer_size = buffer_size
        # Per-metric-type circular buffers
        self._histories: dict[str, MetricHistory] = {}
    
    def _get_or_create_history(self, metric_type: str) -> MetricHistory:
        """Get or initialize circular buffer for a metric type."""
        if metric_type not in self._histories:
            self._histories[metric_type] = MetricHistory(max_size=self._buffer_size)
        return self._histories[metric_type]
    
    def add_reading(
        self,
        metric_type: str,
        value: float,
        timestamp: datetime | None = None
    ) -> None:
        """Add a sensor reading to the history for this metric type."""
        history = self._get_or_create_history(metric_type)
        history.add(value, timestamp)
    
    def compute_trend(self, metric_type: str) -> TrendIndicator | None:
        """Compute trend indicator from accumulated readings.
        
        Returns None if insufficient data or metric type unknown.
        """
        if metric_type not in self._histories:
            return None
        
        history = self._histories[metric_type]
        readings = history.get_readings(min_points=3)
        if readings is None:
            return None
        
        # Linear regression: time (minutes) vs value
        # Normalize time to start at 0 for numerical stability
        base_time = readings[0].timestamp
        times = [(r.timestamp - base_time).total_seconds() / 60.0 for r in readings]
        values = [r.value for r in readings]
        
        # Calculate slope using simple linear regression
        try:
            slope = self._linear_regression_slope(times, values)
        except statistics.StatisticsError:
            # Insufficient variance to compute trend
            return None
        
        # Categorize direction based on thresholds
        direction = self._categorize_direction(metric_type, slope)
        
        # Calculate confidence based on data quality
        confidence = self._calculate_confidence(readings, slope)
        
        return TrendIndicator(
            metric_type=metric_type,
            direction=direction,
            magnitude=slope,
            confidence=confidence,
            data_points=len(readings),
        )
    
    def _linear_regression_slope(self, x: list[float], y: list[float]) -> float:
        """Compute slope using simple linear regression.
        
        POC v1: Simple least squares (no outlier rejection)
        BACKLOG: Add robust regression (RANSAC) or Kalman filter
        """
        n = len(x)
        if n < 2:
            raise statistics.StatisticsError("Need at least 2 points")
        
        # Using statistics module for correlation and variance
        try:
            # Standardize to avoid numerical issues
            x_mean = statistics.mean(x)
            y_mean = statistics.mean(y)
            
            # Compute covariance and variance
            cov = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
            var_x = sum((xi - x_mean) ** 2 for xi in x)
            
            if var_x == 0:
                raise statistics.StatisticsError("No variance in time values")
            
            slope = cov / var_x
            return slope
            
        except statistics.StatisticsError:
            raise
    
    def _categorize_direction(self, metric_type: str, slope: float) -> TrendDirection:
        """Categorize slope into trend direction based on metric-specific thresholds.
        
        POC v1: Hardcoded thresholds from TREND_THRESHOLDS
        BACKLOG: Make configurable and add metric-specific logic
        """
        thresholds = TREND_THRESHOLDS.get(metric_type, {
            "rising_fast": 2.0,
            "rising": 0.5,
            "stable": -0.5,
            "falling": -2.0,
        })
        
        # Determine direction based on thresholds
        rising_fast = thresholds.get("rising_fast", 2.0)
        rising = thresholds.get("rising", 0.5)
        falling_fast = thresholds.get("falling_fast", -2.0)
        falling = thresholds.get("falling", -0.5)
        
        # Apply hysteresis: use different thresholds depending on direction
        if slope >= rising_fast:
            return "rising_fast"
        elif slope >= rising:
            return "rising"
        elif slope <= falling_fast:
            return "falling_fast"
        elif slope <= falling:
            return "falling"
        else:
            return "stable"
    
    def _calculate_confidence(self, readings: list[ReadingPoint], slope: float) -> float:
        """Calculate confidence score based on data quality.
        
        Factors:
        - More data points = higher confidence (max 10 points)
        - Lower variance in residuals = higher confidence
        - More recent data = higher confidence (time decay)
        
        POC v1: Simple heuristic (0.3 + 0.4 * data_coverage + 0.3 * variance_quality)
        BACKLOG: Proper uncertainty quantification (confidence intervals)
        """
        n = len(readings)
        
        # Data coverage factor (max 1.0 at 10 points)
        data_factor = min(n / 10.0, 1.0)
        
        # Time recency factor (weight recent readings more)
        # POC v1: Simple linear recency (most recent = 1.0, oldest = 0.0)
        # Calculate average recency
        if n > 1:
            now = readings[-1].timestamp
            oldest = readings[0].timestamp
            time_span = (now - oldest).total_seconds()
            if time_span > 0:
                recency_weights = [
                    (r.timestamp - oldest).total_seconds() / time_span
                    for r in readings
                ]
                recency_factor = statistics.mean(recency_weights)
            else:
                recency_factor = 1.0
        else:
            recency_factor = 1.0
        
        # Variance quality (lower variance = higher confidence)
        # POC v1: Simplified - just check if we have enough points
        variance_factor = 0.8 if n >= 5 else 0.5 if n >= 3 else 0.3
        
        # Weighted combination
        confidence = 0.3 * data_factor + 0.3 * recency_factor + 0.4 * variance_factor
        
        return round(confidence, 2)
    
    def get_all_trends(self) -> dict[str, TrendIndicator]:
        """Compute trends for all metric types with sufficient data."""
        trends = {}
        for metric_type in self._histories:
            trend = self.compute_trend(metric_type)
            if trend:
                trends[metric_type] = trend
        return trends
    
    def clear(self) -> None:
        """Clear all histories (e.g., on scenario reset)."""
        self._histories.clear()


# Convenience factory for per-cell trend analyzers
def create_cell_trend_analyzer(buffer_size: int = 10) -> TrendAnalyzer:
    """Create a TrendAnalyzer configured for a single grid cell.
    
    Each cell maintains its own TrendAnalyzer for its sensor metrics.
    This keeps memory bounded: 100x100 grid = 10,000 analyzers,
    each with ~10 readings = 100,000 total readings max (~1-2MB).
    """
    return TrendAnalyzer(buffer_size=buffer_size)
