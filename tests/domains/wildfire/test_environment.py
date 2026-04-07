"""Tests for ogar.domains.wildfire.environment."""

import random
import pytest

from domains.wildfire.environment import FireEnvironmentState


@pytest.fixture(autouse=True)
def seed():
    random.seed(42)


class TestFireEnvironmentState:
    def test_defaults(self):
        env = FireEnvironmentState()
        assert env.temperature_c == 30.0
        assert env.humidity_pct == 25.0
        assert env.wind_speed_mps == 5.0

    def test_tick_changes_values(self):
        env = FireEnvironmentState()
        original_temp = env.temperature_c
        env.tick()
        # Values should drift (with seed 42, they will change)
        assert env.temperature_c != original_temp

    def test_tick_clamps_temperature(self):
        env = FireEnvironmentState(temperature_c=50.0, temp_drift=5.0)
        for _ in range(100):
            env.tick()
        assert 15.0 <= env.temperature_c <= 50.0

    def test_tick_clamps_humidity(self):
        env = FireEnvironmentState(humidity_pct=3.0, humidity_drift=5.0)
        for _ in range(100):
            env.tick()
        assert 3.0 <= env.humidity_pct <= 95.0

    def test_tick_clamps_wind_speed(self):
        env = FireEnvironmentState(wind_speed_mps=0.0, wind_speed_drift=2.0)
        for _ in range(100):
            env.tick()
        assert 0.0 <= env.wind_speed_mps <= 30.0

    def test_wind_direction_wraps(self):
        env = FireEnvironmentState(wind_direction_deg=359.0, wind_direction_drift=10.0)
        env.tick()
        assert 0.0 <= env.wind_direction_deg < 360.0

    def test_wind_vector_north(self):
        env = FireEnvironmentState(wind_direction_deg=0.0)
        row_d, col_d = env.wind_vector()
        assert row_d == pytest.approx(-1.0, abs=0.01)
        assert col_d == pytest.approx(0.0, abs=0.01)

    def test_wind_vector_east(self):
        env = FireEnvironmentState(wind_direction_deg=90.0)
        row_d, col_d = env.wind_vector()
        assert row_d == pytest.approx(0.0, abs=0.01)
        assert col_d == pytest.approx(1.0, abs=0.01)

    def test_to_dict(self):
        env = FireEnvironmentState(temperature_c=35.0, humidity_pct=20.0)
        d = env.to_dict()
        assert d["temperature_c"] == 35.0
        assert d["humidity_pct"] == 20.0
        assert "wind_speed_mps" in d
        assert "wind_direction_deg" in d
        assert "pressure_hpa" in d

    def test_repr(self):
        env = FireEnvironmentState()
        r = repr(env)
        assert "FireEnvironmentState" in r
        assert "°C" in r

    def test_is_environment_state_subclass(self):
        from world import EnvironmentState
        assert issubclass(FireEnvironmentState, EnvironmentState)
