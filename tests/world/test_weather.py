"""Tests for ogar.world.weather — WeatherState drift, clamping, wind_vector."""

import math
import random

from world import WeatherState


class TestWeatherDefaults:
    def test_default_values(self):
        w = WeatherState()
        assert w.temperature_c == 30.0
        assert w.humidity_pct == 25.0
        assert w.wind_speed_mps == 5.0
        assert w.wind_direction_deg == 0.0
        assert w.pressure_hpa == 1013.0

    def test_custom_values(self):
        w = WeatherState(temperature_c=40.0, humidity_pct=10.0)
        assert w.temperature_c == 40.0
        assert w.humidity_pct == 10.0

    def test_wind_direction_wraps(self):
        w = WeatherState(wind_direction_deg=400.0)
        assert w.wind_direction_deg == 40.0


class TestWeatherClamping:
    def test_temperature_clamped_to_bounds(self):
        w = WeatherState(temperature_c=15.0, temp_drift=0.0)
        w.temperature_c = 10.0
        w.tick()
        assert w.temperature_c >= 15.0

    def test_humidity_clamped_low(self):
        w = WeatherState(humidity_pct=3.0, humidity_drift=0.0, temp_drift=0.0)
        w.humidity_pct = 0.0
        w.tick()
        assert w.humidity_pct >= 3.0

    def test_wind_speed_non_negative(self):
        w = WeatherState(wind_speed_mps=0.0, wind_speed_drift=0.0)
        w.tick()
        assert w.wind_speed_mps >= 0.0

    def test_pressure_clamped(self):
        w = WeatherState(pressure_hpa=980.0, pressure_drift=0.0, wind_speed_drift=0.0)
        w.pressure_hpa = 970.0
        w.tick()
        assert w.pressure_hpa >= 980.0


class TestWeatherDrift:
    def test_tick_changes_values(self):
        w = WeatherState(temperature_c=30.0, humidity_pct=50.0)
        old_temp = w.temperature_c
        old_hum = w.humidity_pct
        random.seed(99)
        w.tick()
        assert w.temperature_c != old_temp or w.humidity_pct != old_hum

    def test_zero_drift_no_change(self):
        w = WeatherState(
            temperature_c=30.0,
            humidity_pct=50.0,
            wind_speed_mps=5.0,
            pressure_hpa=1013.0,
            temp_drift=0.0,
            humidity_drift=0.0,
            wind_speed_drift=0.0,
            wind_direction_drift=0.0,
            pressure_drift=0.0,
        )
        w.tick()
        assert w.temperature_c == 30.0
        assert w.wind_speed_mps == 5.0
        assert w.pressure_hpa == 1013.0

    def test_humidity_inversely_correlated_with_temp(self):
        random.seed(1)
        w = WeatherState(
            temperature_c=30.0,
            humidity_pct=50.0,
            temp_drift=2.0,
            humidity_drift=0.0,
        )
        w.tick()
        temp_delta = w.temperature_c - 30.0
        hum_delta = w.humidity_pct - 50.0
        if abs(temp_delta) > 0.01:
            assert (temp_delta > 0 and hum_delta < 0) or (temp_delta < 0 and hum_delta > 0)

    def test_multiple_ticks_stay_in_bounds(self):
        w = WeatherState(temp_drift=5.0, humidity_drift=10.0, wind_speed_drift=3.0)
        for _ in range(200):
            w.tick()
        assert 15.0 <= w.temperature_c <= 50.0
        assert 3.0 <= w.humidity_pct <= 95.0
        assert 0.0 <= w.wind_speed_mps <= 30.0
        assert 0.0 <= w.wind_direction_deg < 360.0
        assert 980.0 <= w.pressure_hpa <= 1040.0


class TestWindVector:
    def test_north_wind(self):
        w = WeatherState(wind_direction_deg=0.0)
        row, col = w.wind_vector()
        assert row < 0
        assert abs(col) < 1e-9

    def test_east_wind(self):
        w = WeatherState(wind_direction_deg=90.0)
        row, col = w.wind_vector()
        assert abs(row) < 1e-9
        assert col > 0

    def test_south_wind(self):
        w = WeatherState(wind_direction_deg=180.0)
        row, col = w.wind_vector()
        assert row > 0
        assert abs(col) < 1e-9

    def test_west_wind(self):
        w = WeatherState(wind_direction_deg=270.0)
        row, col = w.wind_vector()
        assert abs(row) < 1e-9
        assert col < 0

    def test_wind_vector_is_unit_length(self):
        w = WeatherState(wind_direction_deg=135.0)
        row, col = w.wind_vector()
        length = math.sqrt(row * row + col * col)
        assert abs(length - 1.0) < 1e-9


class TestWeatherSerialization:
    def test_to_dict(self):
        w = WeatherState(temperature_c=35.0, wind_direction_deg=225.0)
        d = w.to_dict()
        assert d["temperature_c"] == 35.0
        assert d["wind_direction_deg"] == 225.0
        assert "humidity_pct" in d
        assert "pressure_hpa" in d

    def test_repr(self):
        w = WeatherState()
        r = repr(w)
        assert "WeatherState" in r
        assert "temp=" in r
