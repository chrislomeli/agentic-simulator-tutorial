"""
ogar.domains.wildfire.environment

FireEnvironmentState — weather conditions for wildfire simulation.

This is the wildfire domain's implementation of EnvironmentState.
It models temperature, humidity, wind, and pressure with correlated
random-walk drift per tick.

Ported from ogar.world.weather.WeatherState — same logic, now
implementing the EnvironmentState ABC.

Weather evolves each tick via bounded random walk:
  new_value = current_value + random_step
  new_value = clamp(new_value, min, max)

Correlations:
  - Temperature ↔ humidity: inversely correlated (hot = dry)
  - Wind speed ↔ pressure: loosely inverse (low pressure = windier)

Ranges are based on fire-prone regions (southern California,
Mediterranean climates).
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict

from world.environment import EnvironmentState


class FireEnvironmentState(EnvironmentState):
    """
    Weather conditions for wildfire simulation.

    All values are mutable.  The engine calls tick() each simulation
    step to evolve the weather.  Scenario scripts can also set values
    directly to inject weather events (wind shift, temperature spike).
    """

    # ── Weather values ───────────────────────────────────────────
    temperature_c: float = 30.0
    humidity_pct: float = 25.0
    wind_speed_mps: float = 5.0
    wind_direction_deg: float = 0.0
    pressure_hpa: float = 1013.0

    # ── Drift configuration ──────────────────────────────────────
    # How much each variable can change per tick.
    temp_drift: float = 0.5
    humidity_drift: float = 1.0
    wind_speed_drift: float = 0.3
    wind_direction_drift: float = 5.0
    pressure_drift: float = 0.5

    # Pydantic v2 config
    model_config = {"arbitrary_types_allowed": True}

    def tick(self) -> None:
        """
        Advance weather by one simulation step.

        Temperature and humidity are inversely correlated.
        Wind speed and pressure are loosely inversely correlated.
        Wind direction drifts slowly (wraps at 360°).
        """
        # ── Temperature drift ─────────────────────────────────────
        temp_step = random.uniform(-self.temp_drift, self.temp_drift)
        self.temperature_c = self._clamp(
            self.temperature_c + temp_step, 15.0, 50.0
        )

        # ── Humidity drift (inversely correlated with temperature) ─
        humidity_correlation = -temp_step * 0.6
        humidity_step = random.uniform(-self.humidity_drift, self.humidity_drift)
        self.humidity_pct = self._clamp(
            self.humidity_pct + humidity_step + humidity_correlation, 3.0, 95.0
        )

        # ── Wind speed drift ──────────────────────────────────────
        wind_step = random.uniform(-self.wind_speed_drift, self.wind_speed_drift)
        self.wind_speed_mps = self._clamp(
            self.wind_speed_mps + wind_step, 0.0, 30.0
        )

        # ── Wind direction drift (wraps at 360°) ─────────────────
        dir_step = random.uniform(-self.wind_direction_drift, self.wind_direction_drift)
        self.wind_direction_deg = (self.wind_direction_deg + dir_step) % 360.0

        # ── Barometric pressure drift ─────────────────────────────
        pressure_correlation = -wind_step * 0.3
        pressure_step = random.uniform(-self.pressure_drift, self.pressure_drift)
        self.pressure_hpa = self._clamp(
            self.pressure_hpa + pressure_step + pressure_correlation, 980.0, 1040.0
        )

    def wind_vector(self) -> tuple[float, float]:
        """
        Return the wind as a (row_delta, col_delta) unit vector.

        Converts compass degrees into grid movement direction.
        Wind direction 0° (north) means wind pushes northward
        (decreasing row), so the vector is (-1, 0).
        """
        rad = math.radians(self.wind_direction_deg)
        row_delta = -math.cos(rad)   # north component
        col_delta = math.sin(rad)    # east component
        return (row_delta, col_delta)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise current weather for logging / ground truth snapshots."""
        return {
            "temperature_c": round(self.temperature_c, 1),
            "humidity_pct": round(self.humidity_pct, 1),
            "wind_speed_mps": round(self.wind_speed_mps, 1),
            "wind_direction_deg": round(self.wind_direction_deg, 1),
            "pressure_hpa": round(self.pressure_hpa, 1),
        }

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def __repr__(self) -> str:
        return (
            f"FireEnvironmentState("
            f"temp={self.temperature_c:.1f}°C, "
            f"humidity={self.humidity_pct:.1f}%, "
            f"wind={self.wind_speed_mps:.1f}m/s@{self.wind_direction_deg:.0f}°, "
            f"pressure={self.pressure_hpa:.1f}hPa)"
        )
