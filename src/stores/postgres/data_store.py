"""Postgres-backed DataStore facade.

Owns a single `PgGateway` and lazily exposes the five collection repos
(sensors, terrain, wildfires, resources, advisories) as the typed
handles declared in `stores.base.DataStore`.
"""

from __future__ import annotations

from stores.base import DataStore
from stores.postgres.advisory_repo import ResourceAdvisoryRepository
from stores.postgres.gateway import PgGateway
from stores.postgres.resources_repo import TranscriptRepository
from stores.postgres.sensor_repo import SensorRepository
from stores.postgres.terrain_repo import TerrainRepository
from stores.postgres.wildfire_repo import WildfireRepository


class PostgresDataStore(DataStore):
    """DataStore implementation backed by Postgres + pgvector."""

    def __init__(self, pg_gateway: PgGateway | None = None):
        self._pg = pg_gateway or PgGateway()
        self._sensors: SensorRepository | None = None
        self._terrain: TerrainRepository | None = None
        self._wildfires: WildfireRepository | None = None
        self._resources: TranscriptRepository | None = None
        self._advisories: ResourceAdvisoryRepository | None = None

    @property
    def gateway(self) -> PgGateway:
        return self._pg

    @property
    def sensors(self) -> SensorRepository:
        if self._sensors is None:
            self._sensors = SensorRepository(self._pg)
        return self._sensors

    @property
    def terrain(self) -> TerrainRepository:
        if self._terrain is None:
            self._terrain = TerrainRepository(self._pg)
        return self._terrain

    @property
    def wildfires(self) -> WildfireRepository:
        if self._wildfires is None:
            self._wildfires = WildfireRepository(self._pg)
        return self._wildfires

    @property
    def resources(self) -> TranscriptRepository:
        if self._resources is None:
            self._resources = TranscriptRepository(self._pg)
        return self._resources

    @property
    def advisories(self) -> ResourceAdvisoryRepository:
        if self._advisories is None:
            self._advisories = ResourceAdvisoryRepository(self._pg)
        return self._advisories

    def open(self) -> None:
        self._pg.open()

    def close(self) -> None:
        self._pg.close()


_data_store: PostgresDataStore | None = None


def get_postgres_data_store() -> PostgresDataStore:
    """Return the module-level PostgresDataStore singleton, opening on first call."""
    global _data_store
    if _data_store is None:
        _data_store = PostgresDataStore()
        _data_store.open()
    return _data_store
