"""
ogar.resources

Resource management for preparedness assets on the world grid.

Public API:
  ResourceBase          — Pydantic model representing a single resource
  ResourceStatus        — Enum of operational states
  ResourceInventory     — Tracks placement, queries, status transitions
  evaluate_preparedness — Check resource readiness against fire severity SLA
  PreparednessResult    — Evaluation breakdown
  PreparednessPosture   — READY / DEGRADED / CRITICAL / UNABLE
  PreparednessConfig    — Tunable evaluation constants
  SeverityLevel         — LOW / MODERATE / HIGH / EXTREME
  ResponseRequirement   — One SLA table entry
  severity_from_score   — Map sensor filter score → severity level
"""

from resources.base import ResourceBase, ResourceStatus
from resources.evaluator import (
    PreparednessConfig,
    PreparednessPosture,
    PreparednessResult,
    ResourceGap,
    ResponseRequirement,
    SeverityLevel,
    evaluate_preparedness,
    severity_from_score,
)
from resources.inventory import ResourceInventory

__all__ = [
    "PreparednessConfig",
    "PreparednessPosture",
    "PreparednessResult",
    "ResourceBase",
    "ResourceGap",
    "ResourceInventory",
    "ResourceStatus",
    "ResponseRequirement",
    "SeverityLevel",
    "evaluate_preparedness",
    "severity_from_score",
]
