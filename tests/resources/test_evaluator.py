"""Tests for resources.evaluator — preparedness evaluation against SLA."""

import math

from resources.base import ResourceBase
from resources.evaluator import (
    PreparednessConfig,
    PreparednessPosture,
    PreparednessResult,
    ResourceGap,
    ResponseRequirement,
    SeverityLevel,
    _estimate_response_minutes,
    evaluate_preparedness,
    severity_from_score,
)
from resources.inventory import ResourceInventory


def _inv(grid: int = 10) -> ResourceInventory:
    return ResourceInventory(grid_rows=grid, grid_cols=grid)


def _truck(
    rid: str = "truck-1",
    cluster: str = "cluster-north",
    row: int = 2,
    col: int = 2,
) -> ResourceBase:
    return ResourceBase(
        resource_id=rid,
        resource_type="engine",
        cluster_id=cluster,
        grid_row=row,
        grid_col=col,
        capacity=500.0,
        available=500.0,
        mobile=True,
    )


def _helicopter(
    rid: str = "helo-1",
    cluster: str = "cluster-north",
    row: int = 0,
    col: int = 0,
) -> ResourceBase:
    return ResourceBase(
        resource_id=rid,
        resource_type="helicopter",
        cluster_id=cluster,
        grid_row=row,
        grid_col=col,
        capacity=4.0,
        available=4.0,
        mobile=True,
    )


def _crew(
    rid: str = "crew-1",
    cluster: str = "cluster-north",
    row: int = 3,
    col: int = 3,
) -> ResourceBase:
    return ResourceBase(
        resource_id=rid,
        resource_type="crew",
        cluster_id=cluster,
        grid_row=row,
        grid_col=col,
        capacity=1.0,
        available=1.0,
        mobile=True,
    )


# ── severity_from_score ─────────────────────────────────────────────────────

class TestSeverityFromScore:
    def test_low(self):
        assert severity_from_score(0.5) == SeverityLevel.LOW

    def test_moderate(self):
        assert severity_from_score(1.5) == SeverityLevel.MODERATE

    def test_high(self):
        assert severity_from_score(2.5) == SeverityLevel.HIGH

    def test_extreme(self):
        assert severity_from_score(3.5) == SeverityLevel.EXTREME

    def test_zero(self):
        assert severity_from_score(0.0) == SeverityLevel.LOW

    def test_at_threshold_boundary(self):
        # score == 1.0 (0.5 * 2.0) → MODERATE, not LOW
        assert severity_from_score(1.0) == SeverityLevel.MODERATE

    def test_custom_threshold(self):
        # threshold=4.0 → LOW boundary at 2.0
        assert severity_from_score(1.5, trigger_threshold=4.0) == SeverityLevel.LOW
        assert severity_from_score(3.0, trigger_threshold=4.0) == SeverityLevel.MODERATE


# ── _estimate_response_minutes ──────────────────────────────────────────────

class TestEstimateResponseMinutes:
    def test_same_location(self):
        r = _truck(row=5, col=5)
        assert _estimate_response_minutes(r, 5, 5, 5.0) == 0.0

    def test_manhattan_distance(self):
        r = _truck(row=0, col=0)
        # distance = 3 + 4 = 7, × 5.0 = 35.0
        assert _estimate_response_minutes(r, 3, 4, 5.0) == 35.0

    def test_fixed_resource_at_distance_is_infinity(self):
        r = ResourceBase(
            resource_id="hospital-1",
            resource_type="hospital",
            cluster_id="c1",
            grid_row=0,
            grid_col=0,
            mobile=False,
        )
        assert _estimate_response_minutes(r, 5, 5, 5.0) == math.inf

    def test_fixed_resource_at_same_location(self):
        r = ResourceBase(
            resource_id="hospital-1",
            resource_type="hospital",
            cluster_id="c1",
            grid_row=3,
            grid_col=3,
            mobile=False,
        )
        assert _estimate_response_minutes(r, 3, 3, 5.0) == 0.0


# ── evaluate_preparedness ───────────────────────────────────────────────────

class TestEvaluatePreparedness:
    def test_ready_at_low_severity(self):
        inv = _inv()
        inv.register(_truck())
        result = evaluate_preparedness(SeverityLevel.LOW, "cluster-north", inv)
        assert result.posture == PreparednessPosture.READY
        assert len(result.gaps) == 0
        assert len(result.requirements_met) == 1

    def test_unable_with_no_resources(self):
        inv = _inv()
        result = evaluate_preparedness(SeverityLevel.HIGH, "cluster-north", inv)
        assert result.posture == PreparednessPosture.UNABLE

    def test_degraded_partial_coverage(self):
        inv = _inv()
        # HIGH needs: 2 trucks, 1 helicopter, 2 crew
        # Provide trucks and crew but no helicopter
        inv.register(_truck("truck-1"))
        inv.register(_truck("truck-2", row=3, col=3))
        inv.register(_crew("crew-1"))
        inv.register(_crew("crew-2", row=4, col=4))
        result = evaluate_preparedness(
            SeverityLevel.HIGH, "cluster-north", inv,
            target_row=3, target_col=3,
        )
        assert result.posture == PreparednessPosture.DEGRADED
        assert len(result.gaps) == 1
        assert result.gaps[0].requirement.resource_type == "helicopter"

    def test_gaps_report_shortfall(self):
        inv = _inv()
        inv.register(_truck("truck-1"))
        # MODERATE needs 2 trucks — only have 1
        result = evaluate_preparedness(
            SeverityLevel.MODERATE, "cluster-north", inv,
            target_row=2, target_col=2,
        )
        gap = next(g for g in result.gaps if g.requirement.resource_type == "engine")
        assert gap.shortfall == 1

    def test_deployed_resources_not_counted(self):
        inv = _inv()
        inv.register(_truck("truck-1"))
        inv.deploy("truck-1")
        result = evaluate_preparedness(SeverityLevel.LOW, "cluster-north", inv)
        # Deployed truck isn't AVAILABLE
        assert result.posture != PreparednessPosture.READY

    def test_out_of_service_not_counted(self):
        inv = _inv()
        t = _truck("truck-1")
        inv.register(t)
        t.disable()
        result = evaluate_preparedness(SeverityLevel.LOW, "cluster-north", inv)
        assert result.posture != PreparednessPosture.READY

    def test_resources_too_far_away(self):
        inv = _inv()
        # Truck at (0,0), target at (9,9) → distance=18, time=90 min
        inv.register(_truck("truck-1", row=0, col=0))
        result = evaluate_preparedness(
            SeverityLevel.LOW, "cluster-north", inv,
            target_row=9, target_col=9,
        )
        # LOW SLA is 45 min. 90 min > 45 min → gap
        assert result.posture != PreparednessPosture.READY
        assert len(result.gaps) == 1

    def test_cross_cluster_mobile_resources_can_help(self):
        inv = _inv()
        # Truck in cluster-south, close to target in cluster-north
        inv.register(_truck("truck-1", cluster="cluster-south", row=2, col=2))
        result = evaluate_preparedness(
            SeverityLevel.LOW, "cluster-north", inv,
            target_row=3, target_col=3,
        )
        # distance=2, time=10 min < 45 min SLA → counts
        assert result.posture == PreparednessPosture.READY

    def test_custom_config(self):
        tight_sla = PreparednessConfig(
            minutes_per_cell=10.0,  # Slower travel
            sla_table={
                SeverityLevel.LOW: [
                    ResponseRequirement("engine", min_count=1, max_response_minutes=5.0),
                ],
            },
        )
        inv = _inv()
        inv.register(_truck("truck-1", row=0, col=0))
        result = evaluate_preparedness(
            SeverityLevel.LOW, "cluster-north", inv,
            target_row=2, target_col=2,
            config=tight_sla,
        )
        # distance=4, time=40 min > 5 min SLA
        assert result.posture != PreparednessPosture.READY

    def test_critical_posture_when_most_gaps(self):
        inv = _inv()
        # EXTREME needs 4 resource types — provide none
        inv.register(_truck("truck-1"))
        # 1 truck available but EXTREME needs 3 → still a gap
        result = evaluate_preparedness(
            SeverityLevel.EXTREME, "cluster-north", inv,
            target_row=2, target_col=2,
        )
        # All or most requirements unmet
        assert result.posture in (PreparednessPosture.CRITICAL, PreparednessPosture.UNABLE)

    def test_summary_includes_posture(self):
        inv = _inv()
        result = evaluate_preparedness(SeverityLevel.LOW, "cluster-north", inv)
        assert "cluster-north" in result.summary
        assert "LOW" in result.summary

    def test_summary_ready(self):
        inv = _inv()
        inv.register(_truck())
        result = evaluate_preparedness(
            SeverityLevel.LOW, "cluster-north", inv,
            target_row=2, target_col=2,
        )
        assert "READY" in result.summary

    def test_summary_gaps(self):
        inv = _inv()
        result = evaluate_preparedness(SeverityLevel.HIGH, "cluster-north", inv)
        assert "gap" in result.summary.lower()


# ── ResourceGap ─────────────────────────────────────────────────────────────

class TestResourceGap:
    def test_reason_no_resources(self):
        gap = ResourceGap(
            requirement=ResponseRequirement("helicopter", 1, 30.0),
            available_count=0,
            nearest_minutes=None,
        )
        assert "no helicopter" in gap.reason

    def test_reason_insufficient_count(self):
        gap = ResourceGap(
            requirement=ResponseRequirement("engine", 3, 15.0),
            available_count=1,
            nearest_minutes=10.0,
        )
        assert "1/3" in gap.reason

    def test_reason_too_far(self):
        gap = ResourceGap(
            requirement=ResponseRequirement("engine", 1, 15.0),
            available_count=0,
            nearest_minutes=40.0,
        )
        # available_count is 0 (none within SLA), so it shows "no engine"
        assert "no engine" in gap.reason

    def test_shortfall(self):
        gap = ResourceGap(
            requirement=ResponseRequirement("crew", 3, 20.0),
            available_count=1,
            nearest_minutes=5.0,
        )
        assert gap.shortfall == 2


# ── PreparednessResult ──────────────────────────────────────────────────────

class TestPreparednessResult:
    def test_gap_ratio_no_requirements(self):
        result = PreparednessResult(
            cluster_id="c1",
            severity=SeverityLevel.LOW,
            posture=PreparednessPosture.READY,
            requirements_met=[],
            gaps=[],
        )
        assert result.gap_ratio == 0.0

    def test_gap_ratio_half(self):
        req = ResponseRequirement("engine", 1, 30.0)
        gap = ResourceGap(requirement=req, available_count=0, nearest_minutes=None)
        result = PreparednessResult(
            cluster_id="c1",
            severity=SeverityLevel.MODERATE,
            posture=PreparednessPosture.DEGRADED,
            requirements_met=[req],
            gaps=[gap],
        )
        assert result.gap_ratio == 0.5
