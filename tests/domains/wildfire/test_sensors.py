"""Tests for ogar.domains.wildfire.sensors."""

import random
import pytest

from domains.wildfire.sensors import (
    BarometricSensor,
    HumiditySensor,
    SmokeSensor,
    TemperatureSensor,
    ThermalCameraSensor,
    WindSensor,
)


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


def _base_conditions(**overrides) -> dict:
    """Default local conditions for testing — no fire, calm weather."""
    lc = {
        "ambient_temperature_c": 35.0,
        "humidity_pct": 20.0,
        "wind_speed_mps": 5.0,
        "wind_direction_deg": 90.0,
        "wind_vector": (0.0, 1.0),  # east
        "pressure_hpa": 1013.0,
        "own_fire_intensity": 0.0,
        "own_fire_state": "NONE",
        "neighbor_fire_heat": 0.0,
        "nearby_fire_cells": [],
        "grid_rows": 5,
        "grid_cols": 5,
    }
    lc.update(overrides)
    return lc


class TestTemperatureSensor:
    def test_reads_ambient_temperature(self):
        sensor = TemperatureSensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="temp-1", cluster_id="c1",
        )
        reading = sensor.read(_base_conditions())
        assert "celsius" in reading
        assert reading["celsius"] == pytest.approx(35.0, abs=1.0)

    def test_fire_increases_temperature(self):
        sensor = TemperatureSensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="temp-1", cluster_id="c1",
        )
        lc = _base_conditions(own_fire_intensity=0.8)
        reading = sensor.read(lc)
        # Should be well above ambient (35 + 0.8*40 = 67)
        assert reading["celsius"] > 60.0

    def test_neighbor_fire_adds_heat(self):
        sensor = TemperatureSensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="temp-1", cluster_id="c1",
        )
        lc = _base_conditions(neighbor_fire_heat=1.0)
        reading = sensor.read(lc)
        # Should be above ambient (35 + 1.0*15 = 50)
        assert reading["celsius"] > 45.0


class TestHumiditySensor:
    def test_reads_humidity(self):
        sensor = HumiditySensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="hum-1", cluster_id="c1",
        )
        reading = sensor.read(_base_conditions())
        assert reading["relative_humidity_pct"] == pytest.approx(20.0, abs=1.0)

    def test_has_location(self):
        sensor = HumiditySensor(
            grid_row=1, grid_col=3, noise_std=0.0,
            source_id="hum-2", cluster_id="c1",
        )
        assert sensor.location == (1, 3)


class TestWindSensor:
    def test_reads_wind(self):
        sensor = WindSensor(
            grid_row=2, grid_col=2,
            speed_noise_std=0.0, direction_noise_std=0.0,
            source_id="wind-1", cluster_id="c1",
        )
        reading = sensor.read(_base_conditions())
        assert reading["speed_mps"] == pytest.approx(5.0, abs=0.5)
        assert "direction_deg" in reading

    def test_has_location(self):
        sensor = WindSensor(
            grid_row=3, grid_col=1,
            source_id="wind-2", cluster_id="c1",
        )
        assert sensor.location == (3, 1)


class TestSmokeSensor:
    def test_baseline_with_no_fire(self):
        sensor = SmokeSensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="smoke-1", cluster_id="c1",
        )
        reading = sensor.read(_base_conditions())
        # No fire — should be near baseline (5.0)
        assert reading["pm25_ugm3"] == pytest.approx(5.0, abs=1.0)

    def test_fire_increases_smoke(self):
        sensor = SmokeSensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="smoke-1", cluster_id="c1",
        )
        lc = _base_conditions(nearby_fire_cells=[
            {"row": 2, "col": 3, "intensity": 0.8, "distance": 1.0, "dr": 0, "dc": -1},
        ])
        reading = sensor.read(lc)
        # Smoke should be noticeably above the 5.0 baseline
        assert reading["pm25_ugm3"] > 7.0


class TestBarometricSensor:
    def test_reads_pressure(self):
        sensor = BarometricSensor(
            grid_row=2, grid_col=2, noise_std=0.0,
            source_id="baro-1", cluster_id="c1",
        )
        reading = sensor.read(_base_conditions())
        assert reading["pressure_hpa"] == pytest.approx(1013.0, abs=1.0)

    def test_has_location(self):
        sensor = BarometricSensor(
            grid_row=4, grid_col=0, noise_std=0.0,
            source_id="baro-2", cluster_id="c1",
        )
        assert sensor.location == (4, 0)


class TestThermalCameraSensor:
    def test_returns_grid(self):
        sensor = ThermalCameraSensor(
            top_row=0, left_col=0,
            view_rows=3, view_cols=3, noise_std=0.0,
            source_id="cam-1", cluster_id="c1",
        )
        lc = _base_conditions(cell_grid=[
            [{"fire_intensity": 0.0}] * 3 for _ in range(3)
        ])
        reading = sensor.read(lc)
        assert "grid_celsius" in reading
        assert len(reading["grid_celsius"]) == 3
        assert len(reading["grid_celsius"][0]) == 3

    def test_fire_shows_as_hot_spot(self):
        cell_grid = [[{"fire_intensity": 0.0}] * 3 for _ in range(3)]
        cell_grid[1][1] = {"fire_intensity": 0.8}
        sensor = ThermalCameraSensor(
            top_row=0, left_col=0,
            view_rows=3, view_cols=3, noise_std=0.0,
            source_id="cam-1", cluster_id="c1",
        )
        lc = _base_conditions(cell_grid=cell_grid)
        reading = sensor.read(lc)
        # Cell (1,1) should be much hotter than ambient
        assert reading["grid_celsius"][1][1] > 150.0
