"""Tests for domains.wildfire.sensors — 6 concrete fire sensor types."""

import pytest

from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FirePhysicsModule
from domains.wildfire.sensors import (
    TemperatureSensor,
    HumiditySensor,
    WindSensor,
    SmokeSensor,
    BarometricSensor,
    ThermalCameraSensor,
)
from world import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid
from transport import SensorEvent


@pytest.fixture
def sensor_engine():
    """Engine with a 5x5 grid, no fire, stable weather for sensor tests."""
    physics = FirePhysicsModule(base_probability=0.0)
    # Zero drift so readings are stable across ticks
    env = FireEnvironmentState(
        temperature_c=30.0,
        humidity_pct=50.0,
        wind_speed_mps=5.0,
        wind_direction_deg=90.0,
        pressure_hpa=1013.0,
        temp_drift=0.0,
        humidity_drift=0.0,
        wind_speed_drift=0.0,
        wind_direction_drift=0.0,
        pressure_drift=0.0,
    )
    grid = GenericTerrainGrid(rows=5, cols=5, initial_state_factory=physics.initial_cell_state)
    return GenericWorldEngine(grid=grid, environment=env, physics=physics)


# ── TemperatureSensor ────────────────────────────────────────────────────────

class TestTemperatureSensor:
    def test_returns_sensor_event(self, sensor_engine):
        s = TemperatureSensor(
            source_id="temp-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2,
        )
        event = s.emit()
        assert isinstance(event, SensorEvent)
        assert event.source_type == "temperature"

    def test_payload_has_celsius(self, sensor_engine):
        s = TemperatureSensor(
            source_id="temp-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, noise_std=0.0,
        )
        event = s.emit()
        assert "celsius" in event.payload
        assert event.payload["unit"] == "C"

    def test_base_temperature_close_to_weather(self, sensor_engine):
        s = TemperatureSensor(
            source_id="temp-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, noise_std=0.0,
        )
        event = s.emit()
        assert abs(event.payload["celsius"] - 30.0) < 1.0

    def test_fire_boosts_temperature(self, sensor_engine):
        ignited = sensor_engine.grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=1.0)
        sensor_engine.inject_state(2, 2, ignited)
        s = TemperatureSensor(
            source_id="temp-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, noise_std=0.0,
        )
        event = s.emit()
        assert event.payload["celsius"] > 50.0

    def test_neighbor_fire_boosts_temperature(self, sensor_engine):
        ignited = sensor_engine.grid.get_cell(2, 3).cell_state.ignited(tick=0, intensity=0.8)
        sensor_engine.inject_state(2, 3, ignited)
        s = TemperatureSensor(
            source_id="temp-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, noise_std=0.0,
        )
        event = s.emit()
        assert event.payload["celsius"] > 30.0


# ── HumiditySensor ───────────────────────────────────────────────────────────

class TestHumiditySensor:
    def test_returns_sensor_event(self, sensor_engine):
        s = HumiditySensor(source_id="hum-1", cluster_id="c1", engine=sensor_engine, grid_row=2, grid_col=2)
        event = s.emit()
        assert isinstance(event, SensorEvent)
        assert event.source_type == "humidity"

    def test_payload_has_humidity_pct(self, sensor_engine):
        s = HumiditySensor(source_id="hum-1", cluster_id="c1", engine=sensor_engine, grid_row=2, grid_col=2, noise_std=0.0)
        event = s.emit()
        assert "relative_humidity_pct" in event.payload

    def test_close_to_weather_humidity(self, sensor_engine):
        s = HumiditySensor(source_id="hum-1", cluster_id="c1", engine=sensor_engine, grid_row=2, grid_col=2, noise_std=0.0)
        event = s.emit()
        assert abs(event.payload["relative_humidity_pct"] - 50.0) < 2.0


# ── WindSensor ───────────────────────────────────────────────────────────────

class TestWindSensor:
    def test_returns_sensor_event(self, sensor_engine):
        s = WindSensor(source_id="wind-1", cluster_id="c1", engine=sensor_engine, grid_row=2, grid_col=2)
        event = s.emit()
        assert isinstance(event, SensorEvent)
        assert event.source_type == "wind"

    def test_payload_has_speed_and_direction(self, sensor_engine):
        s = WindSensor(
            source_id="wind-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, speed_noise_std=0.0, direction_noise_std=0.0,
        )
        event = s.emit()
        assert "speed_mps" in event.payload
        assert "direction_deg" in event.payload


# ── SmokeSensor ──────────────────────────────────────────────────────────────

class TestSmokeSensor:
    def test_returns_sensor_event(self, sensor_engine):
        s = SmokeSensor(
            source_id="smoke-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2,
        )
        event = s.emit()
        assert isinstance(event, SensorEvent)
        assert event.source_type == "smoke"

    def test_no_fire_low_smoke(self, sensor_engine):
        s = SmokeSensor(
            source_id="smoke-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, noise_std=0.0,
        )
        event = s.emit()
        assert event.payload["pm25_ugm3"] < 10.0

    def test_nearby_fire_detects_smoke(self, sensor_engine):
        ignited = sensor_engine.grid.get_cell(2, 3).cell_state.ignited(tick=0, intensity=0.9)
        sensor_engine.inject_state(2, 3, ignited)
        s = SmokeSensor(
            source_id="smoke-1", cluster_id="c1", engine=sensor_engine,
            grid_row=2, grid_col=2, noise_std=0.0,
        )
        event = s.emit()
        assert event.payload["pm25_ugm3"] > 5.0


# ── BarometricSensor ─────────────────────────────────────────────────────────

class TestBarometricSensor:
    def test_returns_sensor_event(self, sensor_engine):
        s = BarometricSensor(source_id="baro-1", cluster_id="c1", engine=sensor_engine, grid_row=2, grid_col=2)
        event = s.emit()
        assert isinstance(event, SensorEvent)
        assert event.source_type == "barometric_pressure"

    def test_payload_has_pressure(self, sensor_engine):
        s = BarometricSensor(source_id="baro-1", cluster_id="c1", engine=sensor_engine, grid_row=2, grid_col=2, noise_std=0.0)
        event = s.emit()
        assert "pressure_hpa" in event.payload
        assert abs(event.payload["pressure_hpa"] - 1013.0) < 2.0


# ── ThermalCameraSensor ──────────────────────────────────────────────────────

class TestThermalCameraSensor:
    def test_returns_sensor_event(self, sensor_engine):
        s = ThermalCameraSensor(
            source_id="thermal-1", cluster_id="c1", engine=sensor_engine,
            top_row=1, left_col=1, view_rows=3, view_cols=3,
        )
        event = s.emit()
        assert isinstance(event, SensorEvent)
        assert event.source_type == "thermal_camera"

    def test_payload_has_grid_celsius(self, sensor_engine):
        s = ThermalCameraSensor(
            source_id="thermal-1", cluster_id="c1", engine=sensor_engine,
            top_row=0, left_col=0, view_rows=3, view_cols=3,
        )
        event = s.emit()
        assert "grid_celsius" in event.payload
        assert len(event.payload["grid_celsius"]) == 3
        assert len(event.payload["grid_celsius"][0]) == 3

    def test_detects_fire_hotspot(self, sensor_engine):
        ignited = sensor_engine.grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=0.9)
        sensor_engine.inject_state(2, 2, ignited)
        s = ThermalCameraSensor(
            source_id="thermal-1", cluster_id="c1", engine=sensor_engine,
            top_row=1, left_col=1, view_rows=3, view_cols=3, noise_std=0.0,
        )
        event = s.emit()
        grid = event.payload["grid_celsius"]
        # Cell (2,2) is at relative position (1,1) in the 3x3 view starting at (1,1)
        assert grid[1][1] > 100.0
