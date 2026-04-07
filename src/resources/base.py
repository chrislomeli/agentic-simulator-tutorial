"""
ogar.resources.base

Resource model — preparedness assets that exist on the world grid.

What is a Resource?
───────────────────
A Resource represents a real-world asset that agents reason about when
assessing preparedness.  Examples:

  - Firetruck     : mobile, capacity = gallons of water
  - Ambulance     : mobile, capacity = patients
  - Hospital      : fixed, capacity = beds
  - Helicopter    : mobile, capacity = flight hours remaining
  - Fire station  : fixed, capacity = trucks housed

Resources are NOT sensors (they don't emit readings) and NOT actuators
(they don't execute commands).  They are **queryable world state** —
things that exist on the grid that help the agent answer:

    "Are we prepared for what is happening?"

Design intent
─────────────
ResourceBase is a Pydantic BaseModel, not an ABC.  Resources *are* data.
A firetruck and a hospital have the same interface — they differ in field
values, not in behavior.  Domain-specific semantics (what "capacity"
means) live in metadata and scenario setup.

If a future domain needs custom resource behavior, it can subclass
ResourceBase.  But the framework never requires it.

Status vs. capacity
───────────────────
Status and capacity are deliberately separate concerns:

  status    : operational state of the resource itself
              (is the firetruck running? is the hospital open?)

  capacity  : maximum capability
              (50 beds, 500 gallons, 4 flight hours)

  available : current remaining capability
              (12 beds free, 500 gallons full)

A hospital with 0 beds available is still AVAILABLE (it exists and is
operational).  The agent distinguishes "overloaded" from "closed" by
checking both status and available/capacity.

Mobility
────────
Some resources are fixed (hospitals, fire stations).  Others are mobile
(firetrucks, aircraft).  The `mobile` flag controls whether `deploy()`
can update the resource's grid position.  Fixed resources can still be
deployed (a hospital can be "deployed" to handle a surge) but their
location doesn't change.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Resource status enum ─────────────────────────────────────────────────────

class ResourceStatus(str, Enum):
    """
    Operational state of a resource.

    Using str as the mixin means ResourceStatus.AVAILABLE == "AVAILABLE"
    is True, which simplifies logging and JSON serialisation.
    """
    AVAILABLE       = "AVAILABLE"        # Ready to deploy
    DEPLOYED        = "DEPLOYED"         # Currently in use at an incident
    EN_ROUTE        = "EN_ROUTE"         # Moving to a new location (mobile only)
    OUT_OF_SERVICE  = "OUT_OF_SERVICE"   # Broken, refueling, offline


# ── Resource base model ──────────────────────────────────────────────────────

class ResourceBase(BaseModel):
    """
    A preparedness asset on the world grid.

    Create instances directly — no subclass required:

        firetruck = ResourceBase(
            resource_id="firetruck-7",
            resource_type="firetruck",
            cluster_id="cluster-south",
            grid_row=8, grid_col=3,
            capacity=500.0,
            available=500.0,
            mobile=True,
            metadata={"unit": "gallons", "crew_size": 4},
        )

    Fields
    ──────
    resource_id   : Stable identifier. Unique within the system.
                    e.g. "firetruck-7", "hospital-central".

    resource_type : Opaque string tag for the kind of resource.
                    e.g. "firetruck", "hospital", "helicopter".
                    Tools and agents use this to filter and reason.

    cluster_id    : Which cluster this resource is assigned to.
                    Same routing concept as sensors — lets agents
                    query "what resources does my cluster have?"

    status        : Current operational state (ResourceStatus enum).

    grid_row      : Row position on the world grid.
    grid_col      : Column position on the world grid.

    capacity      : Maximum capability.  Units are domain-specific:
                    500 gallons for a firetruck, 50 beds for a hospital.
                    Stored in metadata["unit"] for documentation.

    available     : Current remaining capability.  Must be 0 ≤ available ≤ capacity.

    mobile        : Whether this resource can change grid position.
                    Hospitals are fixed.  Firetrucks are mobile.

    metadata      : Optional dict for domain-specific extras.
                    e.g. {"unit": "gallons", "crew_size": 4, "model": "Type 1"}
    """

    # ── Identity ──────────────────────────────────────────────────────
    resource_id: str = Field(
        description="Stable unique identifier. e.g. 'firetruck-7'."
    )
    resource_type: str = Field(
        description="Opaque type tag. e.g. 'firetruck', 'hospital'."
    )
    cluster_id: str = Field(
        description="Routing key — which cluster this resource belongs to."
    )

    # ── Operational state ─────────────────────────────────────────────
    status: ResourceStatus = Field(
        default=ResourceStatus.AVAILABLE,
        description="Current operational state of the resource."
    )

    # ── Location ──────────────────────────────────────────────────────
    grid_row: int = Field(
        description="Row position on the world grid."
    )
    grid_col: int = Field(
        description="Column position on the world grid."
    )

    # ── Capacity ──────────────────────────────────────────────────────
    capacity: float = Field(
        default=1.0,
        ge=0.0,
        description="Maximum capability. Units are domain-specific."
    )
    available: float = Field(
        default=1.0,
        ge=0.0,
        description="Current remaining capability. 0 ≤ available ≤ capacity."
    )

    # ── Mobility ──────────────────────────────────────────────────────
    mobile: bool = Field(
        default=False,
        description="Whether this resource can change grid position."
    )

    # ── Domain extras ─────────────────────────────────────────────────
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific extras. e.g. {'unit': 'gallons', 'crew_size': 4}."
    )

    # ── Pydantic config ──────────────────────────────────────────────
    model_config = {"use_enum_values": False}

    # ── State transitions ────────────────────────────────────────────

    def deploy(
        self,
        row: Optional[int] = None,
        col: Optional[int] = None,
    ) -> None:
        """
        Transition to DEPLOYED status.

        For mobile resources, optionally update grid position.
        For fixed resources, row/col are ignored.

        Raises ValueError if the resource is OUT_OF_SERVICE.
        """
        if self.status == ResourceStatus.OUT_OF_SERVICE:
            raise ValueError(
                f"Resource {self.resource_id!r} is OUT_OF_SERVICE and cannot be deployed"
            )
        self.status = ResourceStatus.DEPLOYED
        if self.mobile and row is not None and col is not None:
            self.grid_row = row
            self.grid_col = col
        logger.debug(
            "Resource %s deployed at (%d, %d)",
            self.resource_id, self.grid_row, self.grid_col,
        )

    def send_en_route(
        self,
        row: int,
        col: int,
    ) -> None:
        """
        Transition a mobile resource to EN_ROUTE toward a destination.

        Updates grid position to the destination.  In a real system
        the position would update incrementally — here we set the
        destination immediately for simplicity.

        Raises ValueError if the resource is not mobile or is OUT_OF_SERVICE.
        """
        if not self.mobile:
            raise ValueError(
                f"Resource {self.resource_id!r} is not mobile — cannot send en route"
            )
        if self.status == ResourceStatus.OUT_OF_SERVICE:
            raise ValueError(
                f"Resource {self.resource_id!r} is OUT_OF_SERVICE"
            )
        self.status = ResourceStatus.EN_ROUTE
        self.grid_row = row
        self.grid_col = col
        logger.debug(
            "Resource %s en route to (%d, %d)",
            self.resource_id, row, col,
        )

    def release(self) -> None:
        """
        Transition back to AVAILABLE.

        Called when a resource finishes its deployment and is ready
        for the next assignment.
        """
        self.status = ResourceStatus.AVAILABLE
        logger.debug("Resource %s released → AVAILABLE", self.resource_id)

    def disable(self) -> None:
        """Transition to OUT_OF_SERVICE."""
        self.status = ResourceStatus.OUT_OF_SERVICE
        logger.debug("Resource %s → OUT_OF_SERVICE", self.resource_id)

    # ── Capacity management ──────────────────────────────────────────

    def consume(self, amount: float) -> float:
        """
        Reduce available capacity by `amount`.

        Returns the actual amount consumed (may be less than requested
        if available < amount).  Never goes below 0.

        Example: firetruck.consume(100)  # use 100 gallons
        """
        actual = min(amount, self.available)
        self.available -= actual
        logger.debug(
            "Resource %s consumed %.1f (available: %.1f/%.1f)",
            self.resource_id, actual, self.available, self.capacity,
        )
        return actual

    def restore(self, amount: float) -> float:
        """
        Increase available capacity by `amount`.

        Returns the actual amount restored (capped at capacity).
        Never exceeds capacity.

        Example: firetruck.restore(500)  # refill to full
        """
        headroom = self.capacity - self.available
        actual = min(amount, headroom)
        self.available += actual
        logger.debug(
            "Resource %s restored %.1f (available: %.1f/%.1f)",
            self.resource_id, actual, self.available, self.capacity,
        )
        return actual

    # ── Derived properties ───────────────────────────────────────────

    @property
    def utilization(self) -> float:
        """
        Fraction of capacity currently in use: 1.0 - (available / capacity).

        Returns 0.0 if capacity is 0 (resource has no measurable capacity).
        """
        if self.capacity <= 0:
            return 0.0
        return 1.0 - (self.available / self.capacity)

    @property
    def is_available(self) -> bool:
        """True if the resource is AVAILABLE and has remaining capacity."""
        return self.status == ResourceStatus.AVAILABLE and self.available > 0

    # ── Serialisation ────────────────────────────────────────────────

    def to_summary_dict(self) -> Dict[str, Any]:
        """
        Compact summary for ground truth snapshots and LLM tool responses.

        Includes all fields an agent or evaluator would need to reason
        about this resource without the full Pydantic model overhead.
        """
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "cluster_id": self.cluster_id,
            "status": self.status.value,
            "grid_row": self.grid_row,
            "grid_col": self.grid_col,
            "capacity": self.capacity,
            "available": self.available,
            "utilization": round(self.utilization, 3),
            "mobile": self.mobile,
        }

    # ── Repr ─────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"ResourceBase("
            f"id={self.resource_id!r}, "
            f"type={self.resource_type!r}, "
            f"status={self.status.value}, "
            f"at=({self.grid_row},{self.grid_col}), "
            f"avail={self.available}/{self.capacity})"
        )
