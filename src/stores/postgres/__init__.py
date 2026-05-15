"""Postgres-backed implementation of the stores facade."""

from stores.postgres.advisory_repo import ResourceAdvisoryRepository
from stores.postgres.data_store import PostgresDataStore
from stores.postgres.gateway import PgGateway, get_pg_gateway
from stores.postgres.resources_repo import TranscriptRepository
from stores.postgres.sensor_repo import SensorRepository
from stores.postgres.terrain_repo import TerrainRepository
from stores.postgres.wildfire_repo import WildfireRepository

__all__ = [
    "PgGateway",
    "get_pg_gateway",
    "PostgresDataStore",
    "ResourceAdvisoryRepository",
    "SensorRepository",
    "TerrainRepository",
    "TranscriptRepository",
    "WildfireRepository",
]
