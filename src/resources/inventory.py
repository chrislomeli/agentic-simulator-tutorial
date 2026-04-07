"""
ogar.resources.inventory

ResourceInventory — management of resource placement on a grid.

What this is
────────────
The ResourceInventory tracks which resources are placed at which grid
positions and provides queries for assessing preparedness.  It is the
resource-side counterpart to SensorInventory.

The primary experimental knobs are:
  - Change resource density to see how agent preparedness assessments change.
  - Disable resources to simulate attrition.
  - Reduce resources to simulate budget constraints.
  - Query readiness to evaluate agent decision quality.

The inventory is domain-agnostic — it works with any ResourceBase
instance regardless of whether the domain is wildfire, ocean, or
anything else.

Differences from SensorInventory
─────────────────────────────────
  - No emit_all().  Resources don't produce events.
  - No tick behavior.  Resources are static world state.
  - Status transitions instead of failure modes.
  - Capacity tracking and readiness queries.

Placement model
───────────────
Each resource occupies a specific (row, col) on the grid.  Multiple
resources can occupy the same cell (e.g. two firetrucks at the same
station).  Mobile resources can change position via deploy() or
send_en_route().
"""

from __future__ import annotations

import logging
import random
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from resources.base import ResourceBase, ResourceStatus

logger = logging.getLogger(__name__)


class ResourceInventory:
    """
    Manages resource placement, status transitions, and readiness queries.

    Usage
    ─────
      inventory = ResourceInventory(grid_rows=10, grid_cols=10)
      inventory.register(firetruck)
      inventory.register(hospital)

      print(inventory.readiness_summary())
      inventory.deploy("firetruck-7", row=5, col=3)
      inventory.reduce_resources("firetruck", keep_fraction=0.5)
    """

    def __init__(self, grid_rows: int, grid_cols: int) -> None:
        """
        Parameters
        ──────────
        grid_rows : number of rows in the grid (for coverage calculations)
        grid_cols : number of columns in the grid
        """
        self._grid_rows = grid_rows
        self._grid_cols = grid_cols
        self._resources: Dict[str, ResourceBase] = {}           # resource_id → resource
        self._type_index: Dict[str, Set[str]] = {}              # resource_type → {resource_ids}
        self._cluster_index: Dict[str, Set[str]] = {}           # cluster_id → {resource_ids}

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, resource: ResourceBase) -> None:
        """
        Add a resource to the inventory.

        Raises ValueError if:
          - A resource with the same resource_id is already registered
          - The position is out of grid bounds
        """
        if resource.resource_id in self._resources:
            raise ValueError(
                f"Resource {resource.resource_id!r} is already registered"
            )
        if not (0 <= resource.grid_row < self._grid_rows
                and 0 <= resource.grid_col < self._grid_cols):
            raise ValueError(
                f"Position ({resource.grid_row}, {resource.grid_col}) out of bounds "
                f"for grid ({self._grid_rows}×{self._grid_cols})"
            )
        self._resources[resource.resource_id] = resource
        self._type_index.setdefault(resource.resource_type, set()).add(resource.resource_id)
        self._cluster_index.setdefault(resource.cluster_id, set()).add(resource.resource_id)
        logger.debug(
            "Registered resource %s (%s) at (%d, %d) in cluster %s",
            resource.resource_id, resource.resource_type,
            resource.grid_row, resource.grid_col, resource.cluster_id,
        )

    def unregister(self, resource_id: str) -> ResourceBase:
        """
        Remove a resource from the inventory.

        Returns the removed resource.
        Raises KeyError if the resource_id is not registered.
        """
        resource = self._resources.pop(resource_id)

        type_set = self._type_index.get(resource.resource_type)
        if type_set is not None:
            type_set.discard(resource_id)
            if not type_set:
                del self._type_index[resource.resource_type]

        cluster_set = self._cluster_index.get(resource.cluster_id)
        if cluster_set is not None:
            cluster_set.discard(resource_id)
            if not cluster_set:
                del self._cluster_index[resource.cluster_id]

        logger.debug("Unregistered resource %s", resource_id)
        return resource

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_resource(self, resource_id: str) -> ResourceBase:
        """Get a resource by its resource_id. Raises KeyError if not found."""
        return self._resources[resource_id]

    def get_resources_at(self, row: int, col: int) -> List[ResourceBase]:
        """Return all resources placed at the given grid position."""
        return [
            r for r in self._resources.values()
            if r.grid_row == row and r.grid_col == col
        ]

    def all_resources(self) -> List[ResourceBase]:
        """Return all registered resources."""
        return list(self._resources.values())

    @property
    def size(self) -> int:
        """Number of registered resources."""
        return len(self._resources)

    def by_type(self, resource_type: str) -> List[ResourceBase]:
        """Return all resources of a given type."""
        rids = self._type_index.get(resource_type, set())
        return [self._resources[rid] for rid in rids]

    def by_cluster(self, cluster_id: str) -> List[ResourceBase]:
        """Return all resources assigned to a given cluster."""
        rids = self._cluster_index.get(cluster_id, set())
        return [self._resources[rid] for rid in rids]

    def by_status(self, status: ResourceStatus) -> List[ResourceBase]:
        """Return all resources with a given status."""
        return [r for r in self._resources.values() if r.status == status]

    def resource_types(self) -> Set[str]:
        """Return the set of distinct resource_type values currently registered."""
        return set(self._type_index.keys())

    def cluster_ids(self) -> Set[str]:
        """Return the set of distinct cluster_id values currently registered."""
        return set(self._cluster_index.keys())

    # ── Status transitions ───────────────────────────────────────────────────

    def deploy(
        self,
        resource_id: str,
        row: Optional[int] = None,
        col: Optional[int] = None,
    ) -> None:
        """
        Deploy a resource, optionally moving it to a new position.

        Validates grid bounds for mobile resources before delegating
        to ResourceBase.deploy().

        Raises KeyError if resource_id not found.
        Raises ValueError if new position is out of bounds.
        """
        resource = self._resources[resource_id]
        if resource.mobile and row is not None and col is not None:
            if not (0 <= row < self._grid_rows and 0 <= col < self._grid_cols):
                raise ValueError(
                    f"Deploy position ({row}, {col}) out of bounds "
                    f"for grid ({self._grid_rows}×{self._grid_cols})"
                )
        resource.deploy(row=row, col=col)
        logger.info(
            "Deployed resource %s at (%d, %d)",
            resource_id, resource.grid_row, resource.grid_col,
        )

    def release(self, resource_id: str) -> None:
        """
        Release a deployed resource back to AVAILABLE.

        Raises KeyError if resource_id not found.
        """
        self._resources[resource_id].release()
        logger.info("Released resource %s", resource_id)

    # ── Readiness queries ────────────────────────────────────────────────────

    def readiness_summary(self) -> Dict[str, Any]:
        """
        Compute an overall readiness summary across all resources.

        Returns a dict suitable for ground truth snapshots and LLM tools:
          - total_resources: count of all resources
          - by_type: {type: {total, available, deployed, capacity, available_capacity}}
          - by_cluster: {cluster_id: {total, available, types}}
          - by_status: {status: count}
        """
        resources = list(self._resources.values())
        if not resources:
            return {
                "total_resources": 0,
                "by_type": {},
                "by_cluster": {},
                "by_status": {},
            }

        # By type
        by_type: Dict[str, Dict[str, Any]] = {}
        for rtype in self._type_index:
            typed = self.by_type(rtype)
            by_type[rtype] = {
                "total": len(typed),
                "available": sum(1 for r in typed if r.status == ResourceStatus.AVAILABLE),
                "deployed": sum(1 for r in typed if r.status == ResourceStatus.DEPLOYED),
                "out_of_service": sum(1 for r in typed if r.status == ResourceStatus.OUT_OF_SERVICE),
                "total_capacity": sum(r.capacity for r in typed),
                "available_capacity": sum(r.available for r in typed),
            }

        # By cluster
        by_cluster: Dict[str, Dict[str, Any]] = {}
        for cid in self._cluster_index:
            clustered = self.by_cluster(cid)
            by_cluster[cid] = {
                "total": len(clustered),
                "available": sum(1 for r in clustered if r.status == ResourceStatus.AVAILABLE),
                "types": list({r.resource_type for r in clustered}),
            }

        # By status
        by_status = dict(Counter(r.status.value for r in resources))

        return {
            "total_resources": len(resources),
            "by_type": by_type,
            "by_cluster": by_cluster,
            "by_status": by_status,
        }

    def coverage_by_cluster(self) -> Dict[str, List[str]]:
        """
        Return which resource types are present in each cluster.

        Useful for identifying clusters with no fire coverage,
        no medical resources, etc.

        Returns {cluster_id: [resource_type, ...]}.
        """
        result: Dict[str, List[str]] = {}
        for cid in self._cluster_index:
            clustered = self.by_cluster(cid)
            result[cid] = sorted({r.resource_type for r in clustered})
        return result

    # ── Scenario knobs ───────────────────────────────────────────────────────

    def reduce_resources(
        self,
        resource_type: str,
        keep_fraction: float,
    ) -> List[str]:
        """
        Randomly remove resources of a specific type.

        Simulates budget constraints or attrition.

        Parameters
        ──────────
        resource_type  : which type to reduce
        keep_fraction  : fraction to keep (0.0–1.0). 0.5 means remove half.

        Returns the resource_ids of removed resources.
        """
        if not (0.0 <= keep_fraction <= 1.0):
            raise ValueError(f"keep_fraction must be 0.0–1.0, got {keep_fraction}")

        rids = list(self._type_index.get(resource_type, set()))
        keep_count = max(0, int(len(rids) * keep_fraction))
        keep_ids = set(random.sample(rids, min(keep_count, len(rids))))

        removed = []
        for rid in rids:
            if rid not in keep_ids:
                self.unregister(rid)
                removed.append(rid)

        logger.info(
            "Reduced %s resources: kept %d/%d, removed %d",
            resource_type, len(rids) - len(removed), len(rids), len(removed),
        )
        return removed

    def disable_resources(
        self,
        resource_type: str,
        fraction: float,
    ) -> List[str]:
        """
        Randomly set a fraction of resources of a type to OUT_OF_SERVICE.

        Simulates equipment failure or maintenance downtime.

        Returns the resource_ids of disabled resources.
        """
        if not (0.0 <= fraction <= 1.0):
            raise ValueError(f"fraction must be 0.0–1.0, got {fraction}")

        rids = list(self._type_index.get(resource_type, set()))
        count = max(0, int(len(rids) * fraction))
        targets = random.sample(rids, min(count, len(rids)))

        for rid in targets:
            self._resources[rid].disable()

        logger.info(
            "Disabled %d/%d %s resources",
            len(targets), len(rids), resource_type,
        )
        return targets

    def reset_all(self) -> None:
        """Reset all resources to AVAILABLE and restore full capacity."""
        for resource in self._resources.values():
            resource.release()
            resource.restore(resource.capacity)

    # ── Repr ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        available = sum(1 for r in self._resources.values() if r.is_available)
        return (
            f"ResourceInventory("
            f"resources={len(self._resources)}, "
            f"available={available}, "
            f"types={sorted(self._type_index.keys())}, "
            f"grid={self._grid_rows}×{self._grid_cols})"
        )
