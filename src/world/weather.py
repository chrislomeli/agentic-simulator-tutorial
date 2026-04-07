"""
ogar.world.weather

WeatherState — global weather conditions that evolve per tick.

What this models
────────────────
Weather in the simulation is a single set of values that apply
everywhere on the grid at a given tick.  This is a simplification —
real weather varies spatially — but it's sufficient for testing
agent reasoning about wind-driven fire spread, humidity effects,
and weather trend detection.

How weather evolves
────────────────────
Each tick, each weather variable drifts slightly from its current
value using bounded random walk:

  new_value = current_value + random_step
  new_value = clamp(new_value, min, max)

The step size and bounds are configurable per variable.

Correlations between variables:
  - Temperature and humidity are inversely correlated.
    When temperature rises, humidity tends to drop (and vice versa).
    This is physically accurate in dry environments and creates
    the conditions that make fire spread faster.

  - Wind speed and barometric pressure have a loose inverse
    relationship (low pressure → higher wind tendency).

These correlations are approximate — good enough for the agent
to detect patterns, not good enough for a meteorology paper.

Wind direction
──────────────
Wind direction is in compass degrees:
  0   = north (wind blows FROM the south, pushes fire northward)
  90  = east  (wind blows FROM the west, pushes fire eastward)
  180 = south
  270 = west

Wind direction drifts slowly (small random step per tick) to
simulate gradual weather changes.  Scenario scripts can inject
sudden shifts (wind_shift event) to test agent adaptability.

Real-world reference
─────────────────────
These ranges are based on typical values for fire-prone regions
in southern California and Mediterranean climates:
  Temperature: 15–45°C  (NOAA, RAWS weather station data)
  Humidity:    5–80%     (low in fire season, higher in winter)
  Wind:        0–25 m/s (gusts can exceed this; we cap for safety)
  Pressure:    990–1030 hPa (normal surface variation)
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Optional


class WeatherState:
    """
    Global weather conditions for the simulation.

    All values are mutable.  The WorldEngine calls tick() each
    simulation step to evolve the weather forward.  Scenario
    scripts can also set values directly to inject events
    (sudden wind shift, temperature spike, etc.).
    """

    def __init__(
        self,
        *,
        temperature_c: float = 30.0,
        humidity_pct: float = 25.0,
        wind_speed_mps: float = 5.0,
        wind_direction_deg: float = 0.0,
        pressure_hpa: float = 1013.0,
        # ── Drift configuration ──────────────────────────────────
        # These control how much each variable can change per tick.
        # Smaller values = more stable weather.  Larger = more volatile.
        temp_drift: float = 0.5,
        humidity_drift: float = 1.0,
        wind_speed_drift: float = 0.3,
        wind_direction_drift: float = 5.0,
        pressure_drift: float = 0.5,
    ) -> None:
        """
        Parameters
        ──────────
        temperature_c       : Starting temperature in Celsius.
        humidity_pct        : Starting relative humidity as percentage (0–100).
        wind_speed_mps      : Starting wind speed in metres per second.
        wind_direction_deg  : Starting wind direction in compass degrees (0=north).
        pressure_hpa        : Starting barometric pressure in hectopascals.

        *_drift parameters  : Maximum random change per tick for each variable.
                              The actual change each tick is uniform(-drift, +drift)
                              plus any correlation adjustments.
        """
        # ── Current weather values ────────────────────────────────
        self.temperature_c = temperature_c
        self.humidity_pct = humidity_pct
        self.wind_speed_mps = wind_speed_mps
        self.wind_direction_deg = wind_direction_deg % 360.0
        self.pressure_hpa = pressure_hpa

        # ── Drift configuration (stored for tick()) ───────────────
        self._temp_drift = temp_drift
        self._humidity_drift = humidity_drift
        self._wind_speed_drift = wind_speed_drift
        self._wind_direction_drift = wind_direction_drift
        self._pressure_drift = pressure_drift

        # ── Bounds ────────────────────────────────────────────────
        # Clamp values to physically plausible ranges.
        # These are intentionally wide — scenario scripts can narrow
        # them by setting values directly if needed.
        self._bounds = {
            "temperature_c":      (15.0, 50.0),
            "humidity_pct":       (3.0,  95.0),
            "wind_speed_mps":     (0.0,  30.0),
            "wind_direction_deg": (0.0,  360.0),  # wraps, not clamped
            "pressure_hpa":       (980.0, 1040.0),
        }

    def tick(self) -> None:
        """
        Advance weather by one simulation step.

        Each variable drifts by a small random amount, then gets
        clamped to its bounds.  Temperature and humidity are
        inversely correlated: a temperature increase pushes
        humidity down, and vice versa.

        Call this once per WorldEngine.tick() — before fire spread,
        so that the spread module sees the updated weather.
        """
        # ── Temperature drift ─────────────────────────────────────
        temp_step = random.uniform(-self._temp_drift, self._temp_drift)
        self.temperature_c += temp_step
        self.temperature_c = self._clamp("temperature_c", self.temperature_c)

        # ── Humidity drift (inversely correlated with temperature) ─
        # If temperature went up, push humidity down, and vice versa.
        # The correlation factor (0.6) is a tunable constant — it means
        # "60% of the temperature change is reflected as an inverse
        # humidity change."  This is approximate but produces
        # plausible dry-heat / cool-moist patterns.
        humidity_correlation = -temp_step * 0.6
        humidity_step = random.uniform(-self._humidity_drift, self._humidity_drift)
        self.humidity_pct += humidity_step + humidity_correlation
        self.humidity_pct = self._clamp("humidity_pct", self.humidity_pct)

        # ── Wind speed drift ──────────────────────────────────────
        wind_step = random.uniform(-self._wind_speed_drift, self._wind_speed_drift)
        self.wind_speed_mps += wind_step
        self.wind_speed_mps = self._clamp("wind_speed_mps", self.wind_speed_mps)

        # ── Wind direction drift ──────────────────────────────────
        # Wind direction wraps around 360 rather than clamping.
        # A 5° drift per tick means direction shifts slowly,
        # mimicking real weather fronts.
        dir_step = random.uniform(-self._wind_direction_drift, self._wind_direction_drift)
        self.wind_direction_deg = (self.wind_direction_deg + dir_step) % 360.0

        # ── Barometric pressure drift ─────────────────────────────
        # Loose inverse correlation with wind: lower pressure tends
        # to come with higher wind speed.  Very approximate.
        pressure_correlation = -wind_step * 0.3
        pressure_step = random.uniform(-self._pressure_drift, self._pressure_drift)
        self.pressure_hpa += pressure_step + pressure_correlation
        self.pressure_hpa = self._clamp("pressure_hpa", self.pressure_hpa)

    def wind_vector(self) -> tuple[float, float]:
        """
        Return the wind as a (row_delta, col_delta) unit vector.

        This converts compass degrees into grid movement direction.
        The fire spread module uses this to determine which neighbors
        are downwind of a burning cell.

        Wind direction 0° (north) means the wind pushes fire northward
        (decreasing row), so the vector is (-1, 0).

        Returns a normalised vector — multiply by wind_speed_mps
        to get magnitude.
        """
        # Convert compass degrees to radians.
        # Compass: 0=north=up, 90=east=right
        # Math:    0=east=right, pi/2=north=up
        # So compass_rad = pi/2 - math_rad, or equivalently:
        rad = math.radians(self.wind_direction_deg)

        # In grid coordinates:
        #   north = negative row, east = positive col
        # Wind direction N means fire moves north (row decreases).
        row_delta = -math.cos(rad)   # north component
        col_delta = math.sin(rad)    # east component

        return (row_delta, col_delta)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise current weather for logging / sensor input."""
        return {
            "temperature_c": round(self.temperature_c, 1),
            "humidity_pct": round(self.humidity_pct, 1),
            "wind_speed_mps": round(self.wind_speed_mps, 1),
            "wind_direction_deg": round(self.wind_direction_deg, 1),
            "pressure_hpa": round(self.pressure_hpa, 1),
        }

    def _clamp(self, name: str, value: float) -> float:
        """Clamp a value to its configured bounds."""
        lo, hi = self._bounds[name]
        return max(lo, min(hi, value))

    def __repr__(self) -> str:
        return (
            f"WeatherState("
            f"temp={self.temperature_c:.1f}°C, "
            f"humidity={self.humidity_pct:.1f}%, "
            f"wind={self.wind_speed_mps:.1f}m/s@{self.wind_direction_deg:.0f}°, "
            f"pressure={self.pressure_hpa:.1f}hPa)"
        )
