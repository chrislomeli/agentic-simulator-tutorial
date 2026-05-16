"""Backend-agnostic data-access contracts.

`DataStore` is the facade injected into agents and scenario loaders. It
exposes per-collection repository handles (sensors, terrain, wildfires,
resources, advisories), each defined as an ABC so concrete backends
(Postgres today; SQLite/JSON in the future) implement the same surface.

Agent wiring depends on these abstractions only — concrete `PgGateway`
no longer leaks past the `stores/postgres/` subpackage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stores.schemas import Resource, Terrain, WildfireActivity
    from world.domains.wildfire.cell_state import FireCellState
    from world.sensor_inventory import SensorInventory


@dataclass
class TerrainConfig:
    """Physics configuration from the terrain table (optional overrides)."""

    cell_size_ft: float | None = None
    time_step_min: float | None = None
    burn_duration_ticks: int | None = None


class SensorRepository(ABC):
    @abstractmethod
    def fetch_sensors(
        self,
        region_name: str,
        grid_rows: int = 0,
        grid_cols: int = 0,
        grid_layers: int = 1,
        limit: int | None = None,
    ) -> SensorInventory: ...


class TerrainRepository(ABC):
    @abstractmethod
    def fetch_terrain(
        self,
        region_name: str,
        limit: int | None = None,
    ) -> tuple[dict[tuple[int, int, int], Terrain], TerrainConfig]: ...

    @abstractmethod
    def fetch_cell_location(
        self, row: int, col: int, layer: int = 0
    ) -> tuple[float, float] | None: ...

    @abstractmethod
    def build_fire_cell_state(self, terrain: Terrain) -> FireCellState: ...


class WildfireRepository(ABC):
    @abstractmethod
    def fetch_similar_fires(
        self, min_acres: int, max_acres: int, limit: int = 10
    ) -> list[WildfireActivity]: ...

    @abstractmethod
    def fetch_by_fire_name(self, fire_name: str, limit: int = 5) -> list[WildfireActivity]: ...


class ResourceRepository(ABC):
    @abstractmethod
    def save_collection(self, resources: list[Resource]) -> int: ...

    @abstractmethod
    def fetch_resources_with_commitments(
        self, lat: float, long: float, radius_miles: float
    ) -> list[dict]: ...


class AdvisoryRepository(ABC):
    # Records are produced by the agent layer (ResourceAdvisoryRecord). Typed
    # as Any here to keep stores/ free of agent imports.
    @abstractmethod
    def save_advisory(self, advisory: Any) -> int: ...

    @abstractmethod
    def save_advisories(self, advisories: list[Any]) -> int: ...

    @abstractmethod
    def fetch_recent_advisories(
        self, grid_row: int, grid_col: int, limit: int = 10
    ) -> list[Any]: ...


class DataStore(ABC):
    """Top-level facade exposing per-collection repository handles."""

    @property
    @abstractmethod
    def sensors(self) -> SensorRepository: ...

    @property
    @abstractmethod
    def terrain(self) -> TerrainRepository: ...

    @property
    @abstractmethod
    def wildfires(self) -> WildfireRepository: ...

    @property
    @abstractmethod
    def resources(self) -> ResourceRepository: ...

    @property
    @abstractmethod
    def advisories(self) -> AdvisoryRepository: ...

    def open(self) -> None: ...
    def close(self) -> None: ...
