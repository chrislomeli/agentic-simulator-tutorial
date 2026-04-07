"""Tests for ogar.domains.wildfire.sensors."""

import random
import pytest

from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire import FirePhysicsModule
from domains.wildfire.sensors import (
    BarometricSensor,
    HumiditySensor,
    SmokeSensor,
    TemperatureSensor,
    ThermalCameraSensor,
    WindSensor,
)
from world import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


@pytest.fixture
def fire_engine():
    """A small fire engine for sensor tests."""
    physics = FirePhysicsModule()
    env = FireEnvironmentState(temperature_c=35.0, humidity_pct=20.0, wind_speed_mps=5.0)
    grid = GenericTerrainGrid(rows=5, cols=5, initial_state_factory=physics.initial_cell_state)
    return GenericWorldEngine(grid=grid, environment=env, physics=physics)


class TestTemperatureSensor:
    def test_reads_ambient_temperature(self, fire_engine):
        sensor = TemperatureSensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="temp-1", cluster_id="c1",
        )
        reading = sensor.read()
        assert "celsius" in reading
        assert reading["celsius"] == pytest.approx(35.0, abs=1.0)

    def test_fire_increases_temperature(self, fire_engine):
        # Ignite the cell the sensor sits on
        state = fire_engine.grid.get_cell(2, 2).cell_state.ignited(tick=0, intensity=0.8)
        fire_engine.grid.update_cell_state(2, 2, state)

        sensor = TemperatureSensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="temp-1", cluster_id="c1",
        )
        reading = sensor.read()
        # Should be well above ambient (35 + 0.8*40 = 67)
        assert reading["celsius"] > 60.0

    def test_neighbor_fire_adds_heat(self, fire_engine):
        # Ignite a neighbor
        state = fire_engine.grid.get_cell(2, 3).cell_state.ignited(tick=0, intensity=1.0)
        fire_engine.grid.update_cell_state(2, 3, state)

        sensor = TemperatureSensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="temp-1", cluster_id="c1",
        )
        reading = sensor.read()
        # Should be above ambient (35 + 1.0*15 = 50)
        assert reading["celsius"] > 45.0


class TestHumiditySensor:
    def test_reads_humidity(self, fire_engine):
        sensor = HumiditySensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="hum-1", cluster_id="c1",
        )
        reading = sensor.read()
        assert reading["relative_humidity_pct"] == pytest.approx(20.0, abs=1.0)

    def test_has_location(self, fire_engine):
        sensor = HumiditySensor(
            engine=fire_engine, grid_row=1, grid_col=3, noise_std=0.0,
            source_id="hum-2", cluster_id="c1",
        )
        assert sensor.location == (1, 3)


class TestWindSensor:
    def test_reads_wind(self, fire_engine):
        sensor = WindSensor(
            engine=fire_engine, grid_row=2, grid_col=2,
            speed_noise_std=0.0, direction_noise_std=0.0,
            source_id="wind-1", cluster_id="c1",
        )
        reading = sensor.read()
        assert reading["speed_mps"] == pytest.approx(5.0, abs=0.5)
        assert "direction_deg" in reading

    def test_has_location(self, fire_engine):
        sensor = WindSensor(
            engine=fire_engine, grid_row=3, grid_col=1,
            source_id="wind-2", cluster_id="c1",
        )
        assert sensor.location == (3, 1)


class TestSmokeSensor:
    def test_baseline_with_no_fire(self, fire_engine):
        sensor = SmokeSensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="smoke-1", cluster_id="c1",
        )
        reading = sensor.read()
        # No fire — should be near baseline (5.0)
        assert reading["pm25_ugm3"] == pytest.approx(5.0, abs=1.0)

    def test_fire_increases_smoke(self, fire_engine):
        state = fire_engine.grid.get_cell(2, 3).cell_state.ignited(tick=0, intensity=0.8)
        fire_engine.grid.update_cell_state(2, 3, state)

        sensor = SmokeSensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="smoke-1", cluster_id="c1",
        )
        reading = sensor.read()
        assert reading["pm25_ugm3"] > 10.0


class TestBarometricSensor:
    def test_reads_pressure(self, fire_engine):
        sensor = BarometricSensor(
            engine=fire_engine, grid_row=2, grid_col=2, noise_std=0.0,
            source_id="baro-1", cluster_id="c1",
        )
        reading = sensor.read()
        assert reading["pressure_hpa"] == pytest.approx(1013.0, abs=1.0)

    def test_has_location(self, fire_engine):
        sensor = BarometricSensor(
            engine=fire_engine, grid_row=4, grid_col=0, noise_std=0.0,
            source_id="baro-2", cluster_id="c1",
        )
        assert sensor.location == (4, 0)


class TestThermalCameraSensor:
    def test_returns_grid(self, fire_engine):
        sensor = ThermalCameraSensor(
            engine=fire_engine, top_row=0, left_col=0,
            view_rows=3, view_cols=3, noise_std=0.0,
            source_id="cam-1", cluster_id="c1",
        )
        reading = sensor.read()
        assert "grid_celsius" in reading
        assert len(reading["grid_celsius"]) == 3
        assert len(reading["grid_celsius"][0]) == 3

    def test_fire_shows_as_hot_spot(self, fire_engine):
        state = fire_engine.grid.get_cell(1, 1).cell_state.ignited(tick=0, intensity=0.8)
        fire_engine.grid.update_cell_state(1, 1, state)

        sensor = ThermalCameraSensor(
            engine=fire_engine, top_row=0, left_col=0,
            view_rows=3, view_cols=3, noise_std=0.0,
            source_id="cam-1", cluster_id="c1",
        )
        reading = sensor.read()
        # Cell (1,1) should be much hotter than ambient
        assert reading["grid_celsius"][1][1] > 150.0
