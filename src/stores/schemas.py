"""Pydantic models for database tables."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class Resource(BaseModel):
    """Model for the resources table."""

    model_config = ConfigDict(populate_by_name=True)

    resource_id: int | None = None
    source_file: str | None = None
    agency: str | None = None
    cal_file_unit: str | None = None
    unit_id: str | None = None
    resource_category: str | None = None
    resource_type: str | None = None
    nwcg_type: str | None = None
    year: str | None = None
    male: str | None = None
    model: str | None = None
    capacity_water_gal: int | None = None
    pump_gpm: int | None = None
    personnel: int | None = None
    battalion: str | None = None
    station_number: str | None = None
    station_name: str | None = None
    station_address: str | None = None
    mutual_aid_agreement: str | None = None
    lpf_interface_priority: str | None = None
    seasonal: str | None = None
    lat: float | None = None
    long: float | None = None
    notes: str | None = None
    location: str | None = None  # geography(Point, 4326) as WKT string
    distance_miles: float | None = None  # Computed field — excluded from DB operations

    def to_db_row(self) -> tuple:
        """Return tuple for INSERT/UPDATE — computed fields excluded."""
        return (
            self.resource_id,
            self.source_file,
            self.agency,
            self.cal_file_unit,
            self.unit_id,
            self.resource_category,
            self.resource_type,
            self.nwcg_type,
            self.year,
            self.male,
            self.model,
            self.capacity_water_gal,
            self.pump_gpm,
            self.personnel,
            self.battalion,
            self.station_number,
            self.station_name,
            self.station_address,
            self.mutual_aid_agreement,
            self.lpf_interface_priority,
            self.seasonal,
            self.lat,
            self.long,
            self.notes,
            self.location,
        )


class Sensor(BaseModel):
    """Model for the sensors table."""

    model_config = ConfigDict(populate_by_name=True)

    grid_row: int | None = None
    grid_column: int | None = None
    elevation: int | None = None
    sensor_id: str  # PK, required
    sensor_type: str | None = None
    cluster_id: str | None = None
    noise_std: float | None = None
    lat: float | None = None
    long: float | None = None
    location: str | None = None  # geography(Point, 4326) as WKT string
    region: str | None = None


class Terrain(BaseModel):
    """Model for the terrain table."""

    model_config = ConfigDict(populate_by_name=True)

    grid_column: int | None = None
    grid_row: int | None = None
    layer: int | None = None
    cell_key: str | None = None
    terrain: str | None = None
    vegetation: float | None = None
    fuel_moisture: float | None = None
    slope: float | None = None
    cell_size_ft: int | None = None
    time_step_min: float | None = None
    burn_duration_ticks: int | None = None
    lat: float | None = None
    long: float | None = None
    location: str | None = None  # geography(Point, 4326) as WKT string
    region: str | None = None

    # Per-cell weather seed (initial conditions at tick 0)
    temperature_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_mps: float | None = None
    wind_direction_deg: float | None = None
    pressure_hpa: float | None = None


class WildfireActivity(BaseModel):
    """Model for the wildfire_activity table."""

    model_config = ConfigDict(populate_by_name=True)

    imsr_date: date | None = None
    gacc: str | None = None
    gacc_priority: int | None = None
    fire_priority: int | None = None
    new_large_fire_mark: str  # NOT NULL
    fire_name: str | None = None
    unit: str | None = None
    fire_size_acres: int | None = None
    fire_size_change: str | None = None
    percent_containment: int | None = None
    contained_completed: str | None = None
    est_containment_date: str | None = None
    personnel: int | None = None
    personnel_change: str | None = None
    crews: int | None = None
    engines: int | None = None
    helicopters: int | None = None
    structures_lost: int | None = None
    cost_to_date: str | None = None
    origin_ownership: int | None = None
