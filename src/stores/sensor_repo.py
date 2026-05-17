"""Sensor repository — loads sensors from database into SensorInventory."""

from __future__ import annotations

import logging

from domains.wildfire.sensors import (
    BarometricSensor,
    HumiditySensor,
    SmokeSensor,
    TemperatureSensor,
    ThermalCameraSensor,
    WindSensor,
)
from sensors.base import SensorBase
from stores.pg_gateway import PgGateway
from stores.schemas import Sensor
from world.sensor_inventory import SensorInventory

logger = logging.getLogger(__name__)

# Maps DB sensor_type strings to sensor classes
_SENSOR_TYPE_MAP: dict[str, type[SensorBase]] = {
    "temperature": TemperatureSensor,
    "humidity": HumiditySensor,
    "wind": WindSensor,
    "smoke": SmokeSensor,
    "barometric": BarometricSensor,
    "barometric_pressure": BarometricSensor,
    "thermal_camera": ThermalCameraSensor,
}


class SensorRepository:
    """Loads sensor definitions from DB and populates SensorInventory."""

    def __init__(self, pg_gateway: PgGateway):
        self._pg = pg_gateway

    def fetch_sensors(
        self,
        region_name: str,
        grid_rows: int = 0,
        grid_cols: int = 0,
        grid_layers: int = 1,
        limit: int | None = None,
    ) -> SensorInventory:
        """Load sensors for a region and return a populated SensorInventory.

        Parameters
        ----------
        region_name : e.g. 'lpnf_south', 'lpnf_north'
        grid_rows, grid_cols, grid_layers : optional dimensions (default 0 = no bounds)
        limit : Optional max sensors to load (defensive, default None = all)

        Returns
        -------
        SensorInventory populated with sensors from DB
        """
        inventory = SensorInventory(
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            grid_layers=grid_layers,
            validate_bounds=False,  # Allow any sensor positions from DB
        )

        sql = """
            select
                grid_row,
                grid_column,
                elevation,
                sensor_id,
                sensor_type,
                cluster_id,
                noise_std,
                lat,
                long,
                location,
                region
            from sensors
            where region = %s
        """
        params: tuple = (region_name,)
        if limit is not None:
            sql += " limit %s"
            params = (region_name, limit)

        rows = self._pg.fetch_rows(sql, params)

        for row in rows:
            sensor_record = Sensor.model_validate(row)
            sensor = self._create_sensor(sensor_record)
            if sensor:
                inventory.register_auto(sensor)

        logger.info(
            "Loaded %d sensors for region %r into inventory (%d×%d×%d)",
            len(rows),
            region_name,
            grid_rows,
            grid_cols,
            grid_layers,
        )
        return inventory

    def _create_sensor(self, record: Sensor) -> SensorBase | None:
        """Instantiate appropriate sensor subclass from DB record."""
        if not record.sensor_type:
            logger.warning("Sensor %s has no sensor_type, skipping", record.sensor_id)
            return None

        sensor_class = _SENSOR_TYPE_MAP.get(record.sensor_type.lower())
        if not sensor_class:
            logger.warning(
                "Unknown sensor_type %r for sensor %s, skipping",
                record.sensor_type,
                record.sensor_id,
            )
            return None

        # Common kwargs for all sensor types
        kwargs: dict = {
            "source_id": record.sensor_id,
            "cluster_id": record.cluster_id or "default",
            "grid_row": record.grid_row,
            "grid_col": record.grid_column,
            "grid_layer": 0,  # DB schema has no layer column; default to 0
        }

        # Add lat/long to metadata if available
        if record.lat is not None and record.long is not None:
            kwargs["metadata"] = {
                "lat": record.lat,
                "lon": record.long,
                "elevation": record.elevation,
            }

        # Add noise_std if the sensor class supports it
        if record.noise_std is not None and hasattr(sensor_class, "__init__"):
            # Temperature, Humidity, Smoke, Barometric use noise_std
            if sensor_class in (
                TemperatureSensor,
                HumiditySensor,
                SmokeSensor,
                BarometricSensor,
            ):
                kwargs["noise_std"] = record.noise_std
            # WindSensor uses speed_noise_std and direction_noise_std
            elif sensor_class is WindSensor:
                kwargs["speed_noise_std"] = record.noise_std
                kwargs["direction_noise_std"] = record.noise_std * 6  # 6x multiplier

        try:
            return sensor_class(**kwargs)
        except Exception as e:
            logger.exception(
                "Failed to create sensor %s (type=%s): %s",
                record.sensor_id,
                record.sensor_type,
                e,
            )
            return None
