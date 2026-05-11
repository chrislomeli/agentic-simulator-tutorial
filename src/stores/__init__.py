"""stores — All persistence classes, re-exported for convenience.

Import from here:  ``from stores import SensorRepository, ResourceRepository``
"""

from stores.pg_gateway import PgGateway, get_pg_gateway
from stores.sensor_repo import SensorRepository
from stores.terrain_repo import TerrainRepository
from stores.wildfire_repo import WildfireRepository
from stores.resources_repo import TranscriptRepository as ResourceRepository
from stores.schemas import Resource, Sensor, Terrain, WildfireActivity

__all__ = [
    "PgGateway",
    "get_pg_gateway",
    "SensorRepository",
    "TerrainRepository",
    "WildfireRepository",
    "ResourceRepository",
    "Resource",
    "Sensor",
    "Terrain",
    "WildfireActivity",
]