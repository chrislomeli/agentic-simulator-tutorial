"""Pydantic models for database tables."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Resource(BaseModel):
    """Model for the resources table."""

    model_config = ConfigDict(populate_by_name=True)

    resource_id: Optional[int] = None
    source_file: Optional[str] = None
    agency: Optional[str] = None
    cal_file_unit: Optional[str] = None
    unit_id: Optional[str] = None
    resource_category: Optional[str] = None
    resource_type: Optional[str] = None
    nwcg_type: Optional[str] = None
    year: Optional[str] = None
    male: Optional[str] = None
    model: Optional[str] = None
    capacity_water_gal: Optional[int] = None
    pump_gpm: Optional[int] = None
    personnel: Optional[int] = None
    battalion: Optional[str] = None
    station_number: Optional[str] = None
    station_name: Optional[str] = None
    station_address: Optional[str] = None
    mutual_aid_agreement: Optional[str] = None
    lpf_interface_priority: Optional[str] = None
    seasonal: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    notes: Optional[str] = None
    location: Optional[str] = None  # geography(Point, 4326) as WKT string
    distance_miles: Optional[float] = None  # Computed field — excluded from DB operations

    def to_db_row(self) -> tuple:
        """Return tuple for INSERT/UPDATE — computed fields excluded."""
        return (
            self.resource_id, self.source_file, self.agency, self.cal_file_unit, self.unit_id,
            self.resource_category, self.resource_type, self.nwcg_type, self.year, self.male,
            self.model, self.capacity_water_gal, self.pump_gpm, self.personnel, self.battalion,
            self.station_number, self.station_name, self.station_address,
            self.mutual_aid_agreement, self.lpf_interface_priority, self.seasonal,
            self.lat, self.long, self.notes, self.location,
        )


class Sensor(BaseModel):
    """Model for the sensors table."""

    model_config = ConfigDict(populate_by_name=True)

    grid_row: Optional[int] = None
    grid_column: Optional[int] = None
    elevation: Optional[int] = None
    sensor_id: str  # PK, required
    sensor_type: Optional[str] = None
    cluster_id: Optional[str] = None
    noise_std: Optional[float] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    location: Optional[str] = None  # geography(Point, 4326) as WKT string
    region: Optional[str] = None


class Terrain(BaseModel):
    """Model for the terrain table."""

    model_config = ConfigDict(populate_by_name=True)

    grid_column: Optional[int] = None
    grid_row: Optional[int] = None
    layer: Optional[int] = None
    cell_key: Optional[str] = None
    terrain: Optional[str] = None
    vegetation: Optional[float] = None
    fuel_moisture: Optional[float] = None
    slope: Optional[float] = None
    cell_size_ft: Optional[int] = None
    time_step_min: Optional[float] = None
    burn_duration_ticks: Optional[int] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    location: Optional[str] = None  # geography(Point, 4326) as WKT string


class WildfireActivity(BaseModel):
    """Model for the wildfire_activity table."""

    model_config = ConfigDict(populate_by_name=True)

    imsr_date: Optional[date] = None
    gacc: Optional[str] = None
    gacc_priority: Optional[int] = None
    fire_priority: Optional[int] = None
    new_large_fire_mark: str  # NOT NULL
    fire_name: Optional[str] = None
    unit: Optional[str] = None
    fire_size_acres: Optional[int] = None
    fire_size_change: Optional[str] = None
    percent_containment: Optional[int] = None
    contained_completed: Optional[str] = None
    est_containment_date: Optional[str] = None
    personnel: Optional[int] = None
    personnel_change: Optional[str] = None
    crews: Optional[int] = None
    engines: Optional[int] = None
    helicopters: Optional[int] = None
    structures_lost: Optional[int] = None
    cost_to_date: Optional[str] = None
    origin_ownership: Optional[int] = None
