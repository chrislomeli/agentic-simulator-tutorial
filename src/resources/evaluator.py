"""
ogar.resources.evaluator

Preparedness evaluator — are the right resources available within
acceptable response times for the current fire potential level?

This is the operational question the system is designed to answer.
The sensor filter determines *fire potential* (how bad could it get?).
The evaluator determines *preparedness posture* (can we handle it?).

Scoring model
─────────────
Fire potential maps to a severity level.  Each severity level has an
SLA table: what resources are required, how many, and how fast they
must be reachable.  The evaluator checks the inventory against the
SLA and reports gaps.

  severity "high" for cluster-north:
    firetruck  × 2  within 15 min  →  ✓ 3 available
    helicopter × 1  within 30 min  →  ✗ 0 available  ← GAP
    crew       × 2  within 20 min  →  ✓ 2 available

  posture: DEGRADED (1 gap out of 3 requirements)

Response time estimation
────────────────────────
Uses Manhattan distance on the grid × a configurable minutes-per-cell
constant.  This is a rough proxy — good enough for a deterministic
pre-filter, and easy to swap for real routing later.

Public API
──────────
  evaluate_preparedness(severity, cluster_id, inventory, config)
      → PreparednessResult

  PreparednessPosture   — enum: READY / DEGRADED / CRITICAL / UNABLE
  ResponseRequirement   — one line of the SLA table
  PreparednessConfig    — tunable constants (response SLA, speed)
  PreparednessResult    — full evaluation breakdown
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import StrEnum

from resources.base import ResourceBase, ResourceStatus
from resources.inventory import ResourceInventory

logger = logging.getLogger(__name__)


# ── Severity levels ─────────────────────────────────────────────────────────
# Maps directly from the sensor filter's scoring output.

class SeverityLevel(StrEnum):
    LOW      = "low"
    MODERATE = "moderate"
    HIGH     = "high"
    EXTREME  = "extreme"


class PreparednessPosture(StrEnum):
    """Overall readiness assessment for a cluster at a given severity."""
    READY    = "READY"       # All SLA requirements met
    DEGRADED = "DEGRADED"    # Some gaps, but partial coverage exists
    CRITICAL = "CRITICAL"    # Most requirements unmet
    UNABLE   = "UNABLE"      # No resources available at all


# ── SLA table ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResponseRequirement:
    """
    One line of the SLA table: "we need N of resource_type within M minutes."

    Frozen so these can live in a static table without mutation risk.
    """
    resource_type: str
    min_count: int
    max_response_minutes: float


# ── Default SLA table ───────────────────────────────────────────────────────
# What resources each severity level demands.  This is the abstraction
# the user asked for — swap this table to change what "prepared" means.

DEFAULT_SLA: dict[SeverityLevel, list[ResponseRequirement]] = {
    SeverityLevel.LOW: [
        ResponseRequirement("engine", min_count=1, max_response_minutes=45.0),
    ],
    SeverityLevel.MODERATE: [
        ResponseRequirement("engine", min_count=2, max_response_minutes=30.0),
        ResponseRequirement("crew", min_count=1, max_response_minutes=30.0),
    ],
    SeverityLevel.HIGH: [
        ResponseRequirement("engine", min_count=2, max_response_minutes=15.0),
        ResponseRequirement("helicopter", min_count=1, max_response_minutes=30.0),
        ResponseRequirement("crew", min_count=2, max_response_minutes=20.0),
    ],
    SeverityLevel.EXTREME: [
        ResponseRequirement("engine", min_count=3, max_response_minutes=10.0),
        ResponseRequirement("helicopter", min_count=2, max_response_minutes=20.0),
        ResponseRequirement("crew", min_count=3, max_response_minutes=15.0),
        ResponseRequirement("ambulance", min_count=1, max_response_minutes=20.0),
    ],
}


# ── Configuration ───────────────────────────────────────────────────────────

@dataclass
class PreparednessConfig:
    """
    Tunable constants for the preparedness evaluator.

    minutes_per_cell : How many minutes to traverse one grid cell.
                       Manhattan distance × this = estimated response time.
                       Default 5.0 → a 10×10 grid spans ~50 min corner to corner.

    sla_table        : Severity → requirements mapping.  Override to change
                       what "prepared" means for your scenario.

    critical_ratio   : If (gaps / total_requirements) exceeds this,
                       posture is CRITICAL instead of DEGRADED.
    """
    minutes_per_cell: float = 5.0
    sla_table: dict[SeverityLevel, list[ResponseRequirement]] = field(
        default_factory=lambda: dict(DEFAULT_SLA),
    )
    critical_ratio: float = 0.6


DEFAULT_PREPAREDNESS_CONFIG = PreparednessConfig()


# ── Gap detail ──────────────────────────────────────────────────────────────

@dataclass
class ResourceGap:
    """One unmet requirement in the SLA."""
    requirement: ResponseRequirement
    available_count: int
    nearest_minutes: float | None   # None if no resources of this type exist

    @property
    def shortfall(self) -> int:
        return max(0, self.requirement.min_count - self.available_count)

    @property
    def reason(self) -> str:
        if self.available_count == 0:
            return (
                f"no {self.requirement.resource_type} available "
                f"(need {self.requirement.min_count})"
            )
        if self.available_count < self.requirement.min_count:
            return (
                f"only {self.available_count}/{self.requirement.min_count} "
                f"{self.requirement.resource_type} available"
            )
        # Have enough units, but too far away
        return (
            f"{self.requirement.resource_type} nearest in "
            f"{self.nearest_minutes:.0f} min "
            f"(SLA: {self.requirement.max_response_minutes:.0f} min)"
        )


# ── Evaluation result ───────────────────────────────────────────────────────

@dataclass
class PreparednessResult:
    """
    Full preparedness evaluation for a cluster at a given severity.

    Includes the posture assessment, all met/unmet requirements, and
    a human-readable summary suitable for logging or LLM context.
    """
    cluster_id: str
    severity: SeverityLevel
    posture: PreparednessPosture
    requirements_met: list[ResponseRequirement]
    gaps: list[ResourceGap]

    @property
    def total_requirements(self) -> int:
        return len(self.requirements_met) + len(self.gaps)

    @property
    def gap_ratio(self) -> float:
        if self.total_requirements == 0:
            return 0.0
        return len(self.gaps) / self.total_requirements

    @property
    def summary(self) -> str:
        """Human-readable one-liner for logging."""
        if self.posture == PreparednessPosture.READY:
            return (
                f"[{self.cluster_id}] {self.severity.upper()} severity — "
                f"READY ({self.total_requirements}/{self.total_requirements} requirements met)"
            )
        gap_reasons = "; ".join(g.reason for g in self.gaps)
        return (
            f"[{self.cluster_id}] {self.severity.upper()} severity — "
            f"{self.posture} ({len(self.gaps)} gap(s): {gap_reasons})"
        )


# ── Response time estimation ────────────────────────────────────────────────

def _estimate_response_minutes(
    resource: ResourceBase,
    target_row: int,
    target_col: int,
    minutes_per_cell: float,
) -> float:
    """
    Manhattan distance × minutes_per_cell.

    For fixed resources at the target location, response time is 0.
    For mobile resources, it's travel time.  For fixed resources
    elsewhere, they can't move — return infinity.
    """
    distance = abs(resource.grid_row - target_row) + abs(resource.grid_col - target_col)
    if distance == 0:
        return 0.0
    if not resource.mobile:
        return math.inf
    return distance * minutes_per_cell


# ── Severity mapping ───────────────────────────────────────────────────────

def severity_from_score(score: float, trigger_threshold: float = 2.0) -> SeverityLevel:
    """
    Map a sensor filter score to a severity level.

    The thresholds are proportional to trigger_threshold so that
    tuning the filter's sensitivity automatically adjusts severity
    classification.

      score < 0.5 × threshold  →  LOW
      score < 1.0 × threshold  →  MODERATE
      score < 1.5 × threshold  →  HIGH
      score ≥ 1.5 × threshold  →  EXTREME
    """
    if score < trigger_threshold * 0.5:
        return SeverityLevel.LOW
    if score < trigger_threshold:
        return SeverityLevel.MODERATE
    if score < trigger_threshold * 1.5:
        return SeverityLevel.HIGH
    return SeverityLevel.EXTREME


# ── Main evaluator ──────────────────────────────────────────────────────────

def evaluate_preparedness(
    severity: SeverityLevel,
    cluster_id: str,
    inventory: ResourceInventory,
    *,
    target_row: int | None = None,
    target_col: int | None = None,
    config: PreparednessConfig = DEFAULT_PREPAREDNESS_CONFIG,
) -> PreparednessResult:
    """
    Evaluate whether a cluster has adequate resources for a given severity.

    For each SLA requirement at this severity level, checks:
      1. Are there enough AVAILABLE resources of the required type?
      2. Can the nearest ones reach the target within the SLA time?

    If target_row/target_col are not provided, uses the centroid of
    the cluster's resources as the reference point.

    Parameters
    ──────────
    severity     : Fire potential severity level.
    cluster_id   : Which cluster to evaluate.
    inventory    : The resource inventory to query.
    target_row   : Grid row of the incident (optional).
    target_col   : Grid col of the incident (optional).
    config       : Evaluation configuration.

    Returns
    ───────
    PreparednessResult with posture, met requirements, and gaps.
    """
    requirements = config.sla_table.get(severity, [])

    # Default target: centroid of cluster resources
    cluster_resources = inventory.by_cluster(cluster_id)
    if target_row is None or target_col is None:
        if cluster_resources:
            target_row = int(sum(r.grid_row for r in cluster_resources) / len(cluster_resources))
            target_col = int(sum(r.grid_col for r in cluster_resources) / len(cluster_resources))
        else:
            target_row, target_col = 0, 0

    met: list[ResponseRequirement] = []
    gaps: list[ResourceGap] = []

    for req in requirements:
        # Also consider resources from other clusters that could respond
        # (mobile resources only — they can relocate)
        all_typed = [
            r for r in inventory.by_type(req.resource_type)
            if r.status == ResourceStatus.AVAILABLE
        ]

        # Sort by response time to the target
        reachable = []
        nearest_minutes: float | None = None
        for r in all_typed:
            t = _estimate_response_minutes(r, target_row, target_col, config.minutes_per_cell)
            if nearest_minutes is None or t < nearest_minutes:
                nearest_minutes = t
            if t <= req.max_response_minutes:
                reachable.append(r)

        if len(reachable) >= req.min_count:
            met.append(req)
        else:
            gaps.append(ResourceGap(
                requirement=req,
                available_count=len(reachable),
                nearest_minutes=nearest_minutes,
            ))

    # Determine posture
    if not requirements:
        posture = PreparednessPosture.READY
    elif not gaps:
        posture = PreparednessPosture.READY
    elif len(met) == 0:
        posture = PreparednessPosture.UNABLE
    elif len(gaps) / len(requirements) >= config.critical_ratio:
        posture = PreparednessPosture.CRITICAL
    else:
        posture = PreparednessPosture.DEGRADED

    result = PreparednessResult(
        cluster_id=cluster_id,
        severity=severity,
        posture=posture,
        requirements_met=met,
        gaps=gaps,
    )

    logger.info("Preparedness: %s", result.summary)
    return result
