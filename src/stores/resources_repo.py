"""resources_repo.py — Write-through stores for Exchange records."""

from __future__ import annotations

from typing import TypeVar, Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from config import logger
from stores.schemas import Resource
from stores.pg_gateway import PgGateway

T = TypeVar("T", bound=BaseModel)


class TranscriptRepository:
    """Exchange records: writes to JSONL + Postgres; reads from Postgres."""

    def __init__(self, pg_gateway: PgGateway):
        self._pg = pg_gateway

    def save_collection(self, resources: list[Resource]) -> int:
        """Bulk insert resources. Returns number of rows inserted."""
        if not resources:
            return 0

        rows = [r.to_db_row() for r in resources]

        with self._pg.conn() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                insert into resources (
                    resource_id, source_file, agency, cal_file_unit, unit_id,
                    resource_category, resource_type, nwcg_type, year, male,
                    model, capacity_water_gal, pump_gpm, personnel, battalion,
                    station_number, station_name, station_address,
                    mutual_aid_agreement, lpf_interface_priority, seasonal,
                    lat, long, notes, location
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (resource_id) do update set
                    source_file = excluded.source_file,
                    agency = excluded.agency,
                    cal_file_unit = excluded.cal_file_unit,
                    unit_id = excluded.unit_id,
                    resource_category = excluded.resource_category,
                    resource_type = excluded.resource_type,
                    nwcg_type = excluded.nwcg_type,
                    year = excluded.year,
                    male = excluded.male,
                    model = excluded.model,
                    capacity_water_gal = excluded.capacity_water_gal,
                    pump_gpm = excluded.pump_gpm,
                    personnel = excluded.personnel,
                    battalion = excluded.battalion,
                    station_number = excluded.station_number,
                    station_name = excluded.station_name,
                    station_address = excluded.station_address,
                    mutual_aid_agreement = excluded.mutual_aid_agreement,
                    lpf_interface_priority = excluded.lpf_interface_priority,
                    seasonal = excluded.seasonal,
                    lat = excluded.lat,
                    long = excluded.long,
                    notes = excluded.notes,
                    location = excluded.location
                """,
                rows,
            )
            return cur.rowcount

    def fetch_resources(self, lat: float, long: float, radius_miles: float) -> list[Resource]:
        """Return resources within radius_miles of (lat, long), ordered by distance.

        Returns [] on miss or error.
        """
        try:
            rows = self._pg.fetch_rows(
                """
                select
                    resource_id,
                    source_file,
                    agency,
                    cal_file_unit,
                    unit_id,
                    resource_category,
                    resource_type,
                    nwcg_type,
                    year,
                    male,
                    model,
                    capacity_water_gal,
                    pump_gpm,
                    personnel,
                    battalion,
                    station_number,
                    station_name,
                    station_address,
                    mutual_aid_agreement,
                    lpf_interface_priority,
                    seasonal,
                    lat,
                    long,
                    notes,
                    location,
                    ST_Distance(
                        location,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                    ) / 1609.344 as distance_miles
                from resources
                where ST_DWithin(
                    location,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s * 1609.344
                )
                order by distance_miles
                """,
                (long, lat, long, lat, radius_miles),
            )
            return [Resource.model_validate(r) for r in rows] if rows else []
        except Exception as e:
            logger.exception("fetch_resources failed: %s", e)
            return []

