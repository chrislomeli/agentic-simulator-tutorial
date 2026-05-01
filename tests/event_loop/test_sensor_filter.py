"""Tests for event_loop.sensor_filter — scoring model and ScoringFilter."""

from event_loop.sensor_filter import (
    FilterConfig,
    ScoringFilter,
    ScoringResult,
    score_location,
    sensor_filter,
)


def _reading(
    location_id: str = "loc-A",
    temp: float = 28.0,
    hum: float = 35.0,
    wind: float = 4.0,
    fuel: float = 12.0,
    slope: float = 5.0,
) -> dict:
    return {
        "location_id": location_id,
        "temperature_c": temp,
        "humidity_pct": hum,
        "wind_speed_mps": wind,
        "fuel_moisture_pct": fuel,
        "slope_deg": slope,
    }


# ── score_location tests ─────────────────────────────────────────────────────

class TestScoreLocation:
    def test_normal_readings_no_score(self):
        result = score_location(_reading())
        assert result.total_score == 0.0
        assert not result.triggered
        assert result.conditions == []

    def test_single_condition_below_trigger(self):
        # One condition breached, but trigger_threshold=2.0 requires multiple
        result = score_location(_reading(temp=45.0))
        assert result.total_score == 1.0  # temp_weight=1.0
        assert not result.triggered
        assert len(result.conditions) == 1
        assert result.conditions[0][0] == "temperature_c"

    def test_two_conditions_trigger(self):
        # Temperature + humidity both breached → 1.0 + 1.2 = 2.2 > 2.0
        result = score_location(_reading(temp=45.0, hum=10.0))
        assert result.total_score == 2.2
        assert result.triggered
        assert len(result.conditions) == 2

    def test_all_conditions_score(self):
        result = score_location(_reading(temp=45.0, hum=5.0, wind=15.0, fuel=3.0, slope=25.0))
        # 1.0 + 1.2 + 1.0 + 1.5 + 0.8 = 5.5
        assert result.total_score == 5.5
        assert result.triggered
        assert len(result.conditions) == 5

    def test_humidity_inverted_threshold(self):
        # humidity < threshold triggers (lower is worse)
        result = score_location(_reading(hum=10.0))
        assert any(name == "humidity_pct" for name, _, _ in result.conditions)

    def test_fuel_moisture_inverted_threshold(self):
        result = score_location(_reading(fuel=5.0))
        assert any(name == "fuel_moisture_pct" for name, _, _ in result.conditions)

    def test_slope_scores(self):
        result = score_location(_reading(slope=25.0))
        assert any(name == "slope_deg" for name, _, _ in result.conditions)
        assert result.total_score == 0.8  # slope_weight

    def test_custom_config(self):
        config = FilterConfig(trigger_threshold=0.5, temp_high_c=30.0)
        result = score_location(_reading(temp=35.0), config)
        assert result.triggered  # score 1.0 > threshold 0.5

    def test_location_id_preserved(self):
        result = score_location(_reading(location_id="loc-X"))
        assert result.location_id == "loc-X"

    def test_reason_when_triggered(self):
        result = score_location(_reading(temp=45.0, hum=10.0))
        assert "score" in result.reason
        assert "temperature_c" in result.reason

    def test_reason_when_not_triggered(self):
        result = score_location(_reading())
        assert "within normal range" in result.reason


# ── sensor_filter convenience function ────────────────────────────────────────

class TestSensorFilterFunction:
    def test_returns_bool(self):
        assert sensor_filter(_reading()) is False

    def test_triggers_on_multiple_conditions(self):
        assert sensor_filter(_reading(temp=45.0, hum=10.0)) is True

    def test_single_condition_no_trigger(self):
        assert sensor_filter(_reading(temp=45.0)) is False

    def test_custom_config(self):
        config = FilterConfig(trigger_threshold=0.5)
        assert sensor_filter(_reading(temp=45.0), config) is True


# ── ScoringFilter (SensorFilter interface) ────────────────────────────────────

class TestScoringFilter:
    def setup_method(self):
        self.filt = ScoringFilter()

    def test_empty_events_no_trigger(self):
        triggered, _ = self.filt.should_trigger([])
        assert not triggered

    def test_normal_readings_no_trigger(self):
        triggered, reason = self.filt.should_trigger([_reading()])
        assert not triggered
        assert "within normal range" in reason

    def test_multiple_conditions_trigger(self):
        triggered, reason = self.filt.should_trigger([_reading(temp=45.0, hum=10.0)])
        assert triggered
        assert "temperature_c" in reason

    def test_single_condition_no_trigger(self):
        # One condition alone doesn't reach trigger_threshold=2.0
        triggered, _ = self.filt.should_trigger([_reading(temp=45.0)])
        assert not triggered

    def test_rising_temperature_trend_contributes(self):
        # 3 readings with rising temperature approaching threshold
        readings = [
            _reading(temp=30.0),
            _reading(temp=32.5),
            _reading(temp=34.0),  # > 38.0 * 0.85 = 32.3
        ]
        # Trend alone gives 0.7. Still below 2.0, but adds to other scores.
        triggered, _ = self.filt.should_trigger(readings)
        assert not triggered  # trend alone isn't enough

    def test_trend_plus_condition_triggers(self):
        # Fuel moisture breached (1.5) + rising temp trend (0.7) = 2.2 > 2.0
        readings = [
            _reading(temp=30.0, fuel=5.0),
            _reading(temp=32.5, fuel=5.0),
            _reading(temp=34.0, fuel=5.0),
        ]
        triggered, reason = self.filt.should_trigger(readings)
        assert triggered
        assert "fuel_moisture_pct" in reason

    def test_falling_humidity_trend(self):
        # Humidity falling + one condition breached
        readings = [
            _reading(hum=25.0, fuel=5.0),
            _reading(hum=21.0, fuel=5.0),
            _reading(hum=18.0, fuel=5.0),  # < 15.0 * 1.5 = 22.5
        ]
        triggered, _ = self.filt.should_trigger(readings)
        assert triggered  # fuel(1.5) + humidity_trend(0.7) = 2.2 > 2.0

    def test_trend_requires_full_window(self):
        # Only 2 readings — trend window is 3
        readings = [_reading(temp=33.0), _reading(temp=35.0)]
        triggered, _ = self.filt.should_trigger(readings)
        assert not triggered

    def test_custom_config_adjusts_sensitivity(self):
        sensitive = FilterConfig(trigger_threshold=0.5)
        filt = ScoringFilter(sensitive)
        triggered, _ = filt.should_trigger([_reading(temp=45.0)])
        assert triggered  # score 1.0 > threshold 0.5
