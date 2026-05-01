"""
ogar.domains.wildfire.sensors

Fire-specific sensors that produce domain-specific SensorEvent payloads.

These sensors are pure reporting devices.  They receive local_conditions
(a dict sampled from the engine by the publisher's sampler) and add noise
to produce a reading.  They do NOT hold a reference to the engine.

The base class (SensorBase) handles wrapping the payload in a
SensorEvent envelope, applying failure modes, and tracking ticks.
These subclasses only implement read().

Noise model
───────────
Each sensor adds Gaussian noise to its readings.  The noise_std
parameter controls how much noise is added.  Set to 0.0 for
perfect readings (useful for debugging).

Sensor types
────────────
  TemperatureSensor   : ambient temp + fire radiant heat
  HumiditySensor      : relative humidity from weather
  WindSensor          : wind speed and direction
  SmokeSensor         : PM2.5 from fire proximity and wind
  BarometricSensor    : atmospheric pressure
  ThermalCameraSensor : 2D heat grid over a region
"""

from __future__ import annotations

import random
from typing import Any

from sensors.base import SensorBase

# ── Temperature sensor ───────────────────────────────────────────────────────

class TemperatureSensor(SensorBase):
    """
    Reads ambient temperature + fire radiant heat from local conditions.

    Real-world reference:
      RAWS stations report temperature every 10-60 min in °C.
      Fire proximity can raise readings to 80°C+ at close range.
    """

    source_type = "temperature"

    def __init__(
        self,
        *,
        noise_std: float = 0.5,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._noise_std = noise_std

    def read(self, local_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        lc = local_conditions or {}
        base_temp = lc.get("ambient_temperature_c", 25.0)
        own_fire = lc.get("own_fire_intensity", 0.0)
        neighbor_heat = lc.get("neighbor_fire_heat", 0.0)

        heat_boost = own_fire * 40.0 + neighbor_heat * 15.0
        noise = random.gauss(0, self._noise_std)
        celsius = base_temp + heat_boost + noise
        return {"celsius": round(celsius, 1), "unit": "C"}


# ── Humidity sensor ──────────────────────────────────────────────────────────

class HumiditySensor(SensorBase):
    """
    Reads relative humidity from local conditions.

    Real-world reference:
      Standard hygrometers report 0–100% RH.
      Below 20% is extreme fire danger.
    """

    source_type = "humidity"

    def __init__(
        self,
        *,
        noise_std: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._noise_std = noise_std

    def read(self, local_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        lc = local_conditions or {}
        humidity = lc.get("humidity_pct", 50.0) + random.gauss(0, self._noise_std)
        humidity = max(0.0, min(100.0, humidity))
        return {"relative_humidity_pct": round(humidity, 1), "unit": "%"}


# ── Wind sensor ──────────────────────────────────────────────────────────────

class WindSensor(SensorBase):
    """
    Reads wind speed and direction from local conditions.

    Real-world reference:
      Anemometers report wind speed (m/s) and direction (°).
    """

    source_type = "wind"

    def __init__(
        self,
        *,
        speed_noise_std: float = 0.3,
        direction_noise_std: float = 3.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._speed_noise_std = speed_noise_std
        self._direction_noise_std = direction_noise_std

    def read(self, local_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        lc = local_conditions or {}
        speed = max(0.0, lc.get("wind_speed_mps", 0.0) + random.gauss(0, self._speed_noise_std))
        direction = (lc.get("wind_direction_deg", 0.0) + random.gauss(0, self._direction_noise_std)) % 360.0
        return {
            "speed_mps": round(speed, 1),
            "direction_deg": round(direction, 1),
            "unit": "m/s",
        }


# ── Smoke sensor ─────────────────────────────────────────────────────────────

class SmokeSensor(SensorBase):
    """
    Reads PM2.5 particulate density based on nearby fire and wind.

    The reading is derived from total fire intensity in nearby cells,
    modulated by wind direction and distance.

    Real-world reference:
      PM2.5 sensors report in µg/m³.
      Clean air: 0–12, moderate: 12–35, unhealthy: 35–150,
      hazardous: 150+, near wildfire: 500+.
    """

    source_type = "smoke"

    def __init__(
        self,
        *,
        noise_std: float = 2.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._noise_std = noise_std

    def read(self, local_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        lc = local_conditions or {}
        baseline_pm25 = 5.0

        wind_vector = lc.get("wind_vector", (0.0, 0.0))
        wind_row, wind_col = wind_vector
        wind_speed = lc.get("wind_speed_mps", 0.0)
        nearby_fires = lc.get("nearby_fire_cells", [])

        total_smoke = 0.0
        for fire in nearby_fires:
            dist = fire["distance"]
            if dist == 0:
                dist = 0.5

            distance_factor = 1.0 / (1.0 + dist)

            if dist > 0:
                dir_r = fire["dr"] / dist
                dir_c = fire["dc"] / dist
                dot = wind_row * dir_r + wind_col * dir_c
                wind_factor = max(0.1, 0.5 + dot * 0.5)
            else:
                wind_factor = 1.0

            speed_factor = 1.0 + min(wind_speed / 15.0, 1.0)
            contribution = (
                fire["intensity"]
                * distance_factor * wind_factor * speed_factor * 80.0
            )
            total_smoke += contribution

        pm25 = max(0.0, baseline_pm25 + total_smoke + random.gauss(0, self._noise_std))
        return {"pm25_ugm3": round(pm25, 1), "unit": "µg/m³"}


# ── Barometric pressure sensor ──────────────────────────────────────────────

class BarometricSensor(SensorBase):
    """
    Reads atmospheric pressure from local conditions.

    Real-world reference:
      Standard barometers report in hPa. Normal range: 980–1040 hPa.
    """

    source_type = "barometric_pressure"

    def __init__(
        self,
        *,
        noise_std: float = 0.3,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._noise_std = noise_std

    def read(self, local_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        lc = local_conditions or {}
        pressure = lc.get("pressure_hpa", 1013.0) + random.gauss(0, self._noise_std)
        return {"pressure_hpa": round(pressure, 1), "unit": "hPa"}


# ── Thermal camera sensor ───────────────────────────────────────────────────

class ThermalCameraSensor(SensorBase):
    """
    Reads a 2D heat map from a region of the grid.

    Unlike a point sensor, covers a rectangular area and returns
    a grid of temperature values.  Burning cells appear as hot spots.

    This sensor requires local_conditions to include a `cell_grid`
    key (produced by sample_thermal_region in the sampler).

    Real-world reference:
      FLIR thermal cameras produce pixel grids of temperature.
      Near-flame surface: up to 800°C+.
    """

    source_type = "thermal_camera"

    def __init__(
        self,
        *,
        top_row: int,
        left_col: int,
        view_rows: int,
        view_cols: int,
        noise_std: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(grid_row=top_row, grid_col=left_col, **kwargs)
        self._top_row = top_row
        self._left_col = left_col
        self._view_rows = view_rows
        self._view_cols = view_cols
        self._noise_std = noise_std

    def read(self, local_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        lc = local_conditions or {}
        ambient = lc.get("ambient_temperature_c", 25.0)
        cell_grid = lc.get("cell_grid", [])

        heat_grid: list[list[float]] = []
        for r_idx, row_data in enumerate(cell_grid):
            row_temps: list[float] = []
            for c_idx, cell_data in enumerate(row_data):
                fire_heat = cell_data.get("fire_intensity", 0.0) * 200.0
                temp = ambient + fire_heat + random.gauss(0, self._noise_std)
                row_temps.append(round(temp, 1))
            heat_grid.append(row_temps)

        # If no cell_grid provided, produce empty grid of ambient
        if not heat_grid:
            heat_grid = [
                [round(ambient + random.gauss(0, self._noise_std), 1) for _ in range(self._view_cols)]
                for _ in range(self._view_rows)
            ]

        return {
            "grid_celsius": heat_grid,
            "top_row": self._top_row,
            "left_col": self._left_col,
            "view_rows": self._view_rows,
            "view_cols": self._view_cols,
            "unit": "C",
        }
