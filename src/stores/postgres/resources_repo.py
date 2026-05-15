"""resources_repo.py — Write-through stores for Exchange records."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from config import logger
from stores.base import ResourceRepository as ResourceRepositoryBase
from stores.postgres.gateway import PgGateway
from stores.schemas import Resource

T = TypeVar("T", bound=BaseModel)


class TranscriptRepository(ResourceRepositoryBase):
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

    def fetch_resources_with_commitments(
        self, lat: float, long: float, radius_miles: float
    ) -> list[dict]:
        """Return resources within radius with commitment status + fire details.

        Returns [] on miss or error. Each dict contains resource fields,
        distance_miles, status ('available'|'committed'), and fire details
        (if committed). Caller (tool layer) transforms into agent-optimized
        structures.
        """
        logger.info(
            "DATABASE: Fetching resources within %s miles of %s, %s", radius_miles, lat, long
        )

        try:
            rows = self._pg.fetch_rows(
                """
                with commitments as (
                    select
                        ra.resource_id,
                        ra.commitment_level,
                        (now() - make_interval(days => ra.commitment_start_days))::date
                            as commitment_start_date,
                        ra.commitment_length_days,
                        c.fire_id,
                        c.fire_name,
                        c.fire_size_acres,
                        c.percent_containment,
                        c.gacc_priority,
                        c.personnel as fire_personnel,
                        c.crews,
                        c.engines,
                        c.helicopters,
                        c.structures_lost
                    from resource_assignments ra
                    join current_fires c on ra.fire_id = c.fire_id
                )
                select
                    r.resource_id,
                    r.resource_category,
                    r.resource_type,
                    r.nwcg_type,
                    r.personnel,
                    r.battalion,
                    r.station_name,
                    r.lat,
                    r.long,
                    ST_Distance(
                        r.location,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                    ) / 1609.344 as distance_miles,
                    case when c.resource_id is null then 'available' else 'committed' end as status,
                    c.commitment_level,
                    c.commitment_start_date,
                    c.commitment_length_days,
                    c.fire_id,
                    c.fire_name,
                    c.fire_size_acres,
                    c.percent_containment,
                    c.gacc_priority,
                    c.fire_personnel,
                    c.crews,
                    c.engines,
                    c.helicopters,
                    c.structures_lost
                from resources r
                left join commitments c on c.resource_id = r.resource_id
                where ST_DWithin(
                    r.location,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s * 1609.344
                )
                order by distance_miles
                """,
                (long, lat, long, lat, radius_miles),
            )
            return rows or []
        except Exception as e:
            logger.exception("fetch_resources_with_commitments failed: %s", e)
            return []
