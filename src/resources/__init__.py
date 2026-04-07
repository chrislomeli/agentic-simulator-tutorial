"""
ogar.resources

Resource management for preparedness assets on the world grid.

Public API:
  ResourceBase       — Pydantic model representing a single resource
  ResourceStatus     — Enum of operational states
  ResourceInventory  — Tracks placement, queries, status transitions
"""

from resources.base import ResourceBase, ResourceStatus
from resources.inventory import ResourceInventory

__all__ = [
    "ResourceBase",
    "ResourceStatus",
    "ResourceInventory",
]
