"""
domains.wildfire.world_builder.raws

Schema and grid-placement utilities for Remote Automated Weather Stations.

This module is intentionally free of location-specific raw. Station
inventories and cluster assignments live in raw/regions/*.json and are
loaded into RegionProfile instances by regions.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agents.commons.geo import latlon_to_grid


class RawsStation(BaseModel):
    """One Remote Automated Weather Station in the simulated world."""

    stid: str = Field(description="Station ID — real Synoptic STID or stable placeholder")
    name: str
    lat: float
    lon: float
    cluster: str


class PlacedRawsStation(BaseModel):
    """A RAWS station snapped onto a sim-grid cell."""

    station: RawsStation
    row: int
    col: int


def place_raws_on_grid(
    stations: tuple[RawsStation, ...] | list[RawsStation],
    grid_rows: int,
    grid_cols: int,
    bounds: dict,
) -> list[PlacedRawsStation]:
    """
    Snap each station to its containing sim cell via latlon_to_grid.

    Stations outside the bounding box are silently dropped. Compare
    output length to input length to detect drops.
    """
    placed: list[PlacedRawsStation] = []
    for station in stations:
        cell = latlon_to_grid(station.lat, station.lon, grid_rows, grid_cols, bounds)
        if cell is None:
            continue
        row, col = cell
        placed.append(PlacedRawsStation(station=station, row=row, col=col))
    return placed
