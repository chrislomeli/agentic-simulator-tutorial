"""stores — Data-access facade and concrete backend implementations.

The agent layer depends on `DataStore` (an ABC). The Postgres
implementation lives in `stores.postgres`; future SQLite / JSON backends
would sit alongside it. Domain schemas (Resource, Sensor, Terrain,
WildfireActivity) are backend-agnostic and live at the package root.
"""

from stores.base import (
    AdvisoryRepository,
    DataStore,
    ResourceRepository,
    SensorRepository,
    TerrainConfig,
    TerrainRepository,
    WildfireRepository,
)
from stores.mock.data_store import MockDataStore, get_mock_data_store
from stores.schemas import Resource, Sensor, Terrain, WildfireActivity

__all__ = [
    # ABCs (the public contract)
    "AdvisoryRepository",
    "DataStore",
    "ResourceRepository",
    "SensorRepository",
    "TerrainConfig",
    "TerrainRepository",
    "WildfireRepository",
    # Postgres impl entry points
    "MockDataStore",
    "get_mock_data_store",
    # Schemas
    "Resource",
    "Sensor",
    "Terrain",
    "WildfireActivity",
]
