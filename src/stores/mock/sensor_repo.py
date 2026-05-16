"""Mock sensor repository — loads from sensors.json (full LPNF RAWS extract)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from stores.base import SensorRepository as SensorRepositoryBase
from stores.schemas import Sensor
from world.domains.wildfire.sensors import (
    BarometricSensor,
    HumiditySensor,
    SmokeSensor,
    TemperatureSensor,
    ThermalCameraSensor,
    WindSensor,
)
from world.sensor_inventory import SensorInventory
from world.sensors.base import SensorBase

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "sensors.json"

_SENSOR_TYPE_MAP: dict[str, type[SensorBase]] = {
    "temperature": TemperatureSensor,
    "humidity": HumiditySensor,
    "wind": WindSensor,
    "smoke": SmokeSensor,
    "barometric": BarometricSensor,
    "barometric_pressure": BarometricSensor,
    "thermal_camera": ThermalCameraSensor,
}


class MockSensorRepository(SensorRepositoryBase):
    def fetch_sensors(
        self,
        region_name: str,
        grid_rows: int = 0,
        grid_cols: int = 0,
        grid_layers: int = 1,
        limit: int | None = None,
    ) -> SensorInventory:
        inventory = SensorInventory(
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            grid_layers=grid_layers,
            validate_bounds=False,
        )

        rows = json.loads(_DATA_FILE.read_text())
        rows = [r for r in rows if r.get("region") == region_name]
        if limit is not None:
            rows = rows[:limit]

        for row in rows:
            record = Sensor.model_validate(row)
            sensor = self._create_sensor(record)
            if sensor:
                inventory.register_auto(sensor)

        logger.info(
            "Mock: loaded %d sensors for region %r into inventory (%dx%dx%d)",
            len(rows),
            region_name,
            grid_rows,
            grid_cols,
            grid_layers,
        )
        return inventory

    def _create_sensor(self, record: Sensor) -> SensorBase | None:
        if not record.sensor_type:
            return None

        sensor_class = _SENSOR_TYPE_MAP.get(record.sensor_type.lower())
        if not sensor_class:
            logger.warning(
                "Mock: unknown sensor_type %r for %s, skipping",
                record.sensor_type,
                record.sensor_id,
            )
            return None

        kwargs: dict = {
            "source_id": record.sensor_id,
            "cluster_id": record.cluster_id or "default",
            "grid_row": record.grid_row,
            "grid_col": record.grid_column,
            "grid_layer": 0,
        }

        if record.lat is not None and record.long is not None:
            kwargs["metadata"] = {
                "lat": record.lat,
                "lon": record.long,
                "elevation": record.elevation,
            }

        if record.noise_std is not None:
            if sensor_class in (TemperatureSensor, HumiditySensor, SmokeSensor, BarometricSensor):
                kwargs["noise_std"] = record.noise_std
            elif sensor_class is WindSensor:
                kwargs["speed_noise_std"] = record.noise_std
                kwargs["direction_noise_std"] = record.noise_std * 6

        try:
            return sensor_class(**kwargs)
        except Exception as e:
            logger.exception("Mock: failed to create sensor %s: %s", record.sensor_id, e)
            return None
