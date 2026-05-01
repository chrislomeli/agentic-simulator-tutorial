"""
ogar.tools.fire_behavior_tools

LangGraph tools that the supervisor LLM calls to get fire behavior metrics
and resource sizing recommendations based on Rothermel physics.

These tools give the LLM structured access to:
  1. Fire behavior metrics from the Rothermel physics module
     (ROS, flame length, fireline intensity, danger rating).
  2. NWCG resource sizing — which types and quantities are needed at the
     current fireline intensity level.
  3. Gap analysis — what resources are available vs. what's needed.

Tools
─────
  get_fire_behavior      : Current ROS, flame length, intensity, danger rating.
  get_resource_needs     : Which resource types can engage at this intensity.
  compare_resources_to_needs: Available vs. needed — gap analysis.

Design notes
────────────
  - Same module-level state holder pattern as supervisor_tools.py.
  - Fire behavior data comes from _SupervisorToolState.fire_behavior_summary,
    which is populated from the physics module's summarize() output.
  - Resource inventory data comes from _SupervisorToolState.resource_inventory.
  - NWCG catalog and intensity thresholds come from nwcg_resources.py.
"""

from __future__ import annotations

import math
from typing import Any

from langchain_core.tools import tool

from domains.wildfire.nwcg_resources import (
    INTENSITY_THRESHOLDS,
    suppression_category,
)

# ── State accessors ───────────────────────────────────────────────────────────
# Read from the shared supervisor tool state to avoid a separate holder.

def _get_fire_behavior() -> dict[str, Any] | None:
    """Read the fire behavior summary from the supervisor tool state."""
    from tools.supervisor_tools import _state as supervisor_state
    return supervisor_state.fire_behavior_summary


def _get_resource_inventory():
    """Read the ResourceInventory from the supervisor tool state."""
    from tools.supervisor_tools import _state as supervisor_state
    return supervisor_state.resource_inventory


def set_fire_behavior_tool_state(
    fire_behavior_summary: dict[str, Any],
) -> None:
    """Convenience wrapper for standalone testing — sets fire behavior summary."""
    from tools.supervisor_tools import _state as supervisor_state
    supervisor_state.fire_behavior_summary = fire_behavior_summary


def clear_fire_behavior_tool_state() -> None:
    """Convenience wrapper for standalone testing — clears fire behavior summary."""
    from tools.supervisor_tools import _state as supervisor_state
    supervisor_state.fire_behavior_summary = None


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def get_fire_behavior() -> dict[str, Any]:
    """Get current fire behavior metrics from the simulation.

    Returns Rothermel-derived fire behavior metrics for the current tick:
      - avg_ros_ft_min         : mean Rate of Spread across burning cells (ft/min)
      - max_ros_ft_min         : peak Rate of Spread (ft/min)
      - avg_flame_length_ft    : mean flame length (ft)
      - max_fireline_intensity : peak fireline intensity (BTU/ft/s)
      - estimated_acres_hr     : estimated area growth (acres/hr)
      - danger_rating          : Low / Moderate / High / Very High / Extreme
      - suppression_category   : hand_crew / engine / dozer / aerial_only / beyond_suppression

    Returns an error dict if no fire behavior data is available.
    """
    fb = _get_fire_behavior()
    if fb is None:
        return {"error": "No fire behavior data available", "danger_rating": "Unknown"}

    max_fi = fb.get("max_fireline_intensity", 0.0)
    return {
        "avg_ros_ft_min": fb.get("avg_ros_ft_min", 0.0),
        "max_ros_ft_min": fb.get("max_ros_ft_min", 0.0),
        "avg_flame_length_ft": fb.get("avg_flame_length_ft", 0.0),
        "max_fireline_intensity": max_fi,
        "estimated_acres_hr": fb.get("estimated_acres_hr", 0.0),
        "danger_rating": fb.get("danger_rating", "Unknown"),
        "suppression_category": suppression_category(max_fi),
    }


@tool
def get_resource_needs(cluster_id: str | None = None) -> dict[str, Any]:
    """Estimate resource needs based on current fire behavior.

    Uses fireline intensity to determine which resource types can effectively
    engage, and Rate of Spread to estimate how many units are needed to match
    fire perimeter growth.

    Perimeter growth (chains/hr) is estimated as:
      perimeter_chains_hr = ROS (ft/min) × 60 × 2π / 66
    where 66 ft = 1 chain.  This assumes a roughly circular fire expanding
    from its center — a conservative overestimate compared to the actual
    elliptical perimeter.

    Args:
        cluster_id: Optional cluster context.  Currently informational only
                    (future: will look up cluster-specific conditions).

    Returns:
        Dict with:
          - suppression_difficulty : category from INTENSITY_THRESHOLDS
          - max_fireline_intensity : current peak intensity (BTU/ft/s)
          - perimeter_growth_chains_hr: estimated growth rate
          - recommended_resources : list of {nwcg_id, name, quantity, reason}
    """
    fb = _get_fire_behavior()
    if fb is None:
        return {"error": "No fire behavior data available"}

    max_ros = fb.get("max_ros_ft_min", 0.0)
    max_fi = fb.get("max_fireline_intensity", 0.0)
    cat = suppression_category(max_fi)

    # Perimeter growth estimate (chains/hr).
    perimeter_chains_hr = round(max_ros * 60.0 * 2 * math.pi / 66.0, 1)

    recommended: list[dict[str, Any]] = []

    if cat == "hand_crew":
        # < 100 BTU/ft/s — hand crews can work the line.
        needed_production = max(1, math.ceil(perimeter_chains_hr / 15))  # IHC = 15 ch/hr
        recommended.append({
            "nwcg_id": "C-1",
            "name": "Interagency Hotshot Crew (IHC)",
            "quantity": needed_production,
            "reason": (
                f"Fireline intensity {max_fi:.0f} BTU/ft/s is below 100 — "
                "hand crews can directly engage. "
                f"Perimeter growth {perimeter_chains_hr} ch/hr requires "
                f"~{needed_production} IHC (15 ch/hr each)."
            ),
        })
        recommended.append({
            "nwcg_id": "E-3",
            "name": "Wildland Engine (4x4)",
            "quantity": max(1, needed_production),
            "reason": "Engine support for crew water needs and direct attack.",
        })

    elif cat == "engine":
        # 100–500 BTU/ft/s — engines are primary, crews support.
        recommended.append({
            "nwcg_id": "E-3",
            "name": "Wildland Engine (4x4)",
            "quantity": 2,
            "reason": (
                f"Fireline intensity {max_fi:.0f} BTU/ft/s — engine-range "
                "direct attack. 2+ engines for flanking approach."
            ),
        })
        recommended.append({
            "nwcg_id": "C-1",
            "name": "Interagency Hotshot Crew (IHC)",
            "quantity": 1,
            "reason": "Crew for line construction ahead of engines.",
        })

    elif cat == "dozer":
        # 500–1000 BTU/ft/s — dozers for indirect attack.
        recommended.append({
            "nwcg_id": "D-1",
            "name": "Heavy Dozer (D8/D7)",
            "quantity": 1,
            "reason": (
                f"Fireline intensity {max_fi:.0f} BTU/ft/s — too intense for "
                "direct hand attack. Heavy dozer (60 ch/hr) for indirect line."
            ),
        })
        recommended.append({
            "nwcg_id": "E-3",
            "name": "Wildland Engine (4x4)",
            "quantity": 2,
            "reason": "Engines for mop-up and structure protection.",
        })

    elif cat == "aerial_only":
        # 1000–2000 BTU/ft/s — aerial resources needed.
        recommended.append({
            "nwcg_id": "H-1",
            "name": "Heavy Helicopter (Type 1)",
            "quantity": 1,
            "reason": (
                f"Fireline intensity {max_fi:.0f} BTU/ft/s — ground resources "
                "marginal. Helicopter for water drops on hot spots."
            ),
        })
        recommended.append({
            "nwcg_id": "A-1",
            "name": "Large Air Tanker (LAT)",
            "quantity": 1,
            "reason": "Retardant drop to slow spread ahead of planned fireline.",
        })
        recommended.append({
            "nwcg_id": "D-1",
            "name": "Heavy Dozer (D8/D7)",
            "quantity": 2,
            "reason": "Indirect dozer line well ahead of the fire front.",
        })

    else:
        # ≥ 2000 BTU/ft/s — beyond suppression.
        recommended.append({
            "nwcg_id": "A-2",
            "name": "Very Large Air Tanker (VLAT)",
            "quantity": 1,
            "reason": (
                f"Fireline intensity {max_fi:.0f} BTU/ft/s — beyond direct "
                "suppression. VLAT retardant for containment lines only."
            ),
        })
        recommended.append({
            "nwcg_id": "H-1",
            "name": "Heavy Helicopter (Type 1)",
            "quantity": 2,
            "reason": "Structure protection and evacuation support.",
        })

    return {
        "suppression_difficulty": cat,
        "max_fireline_intensity": round(max_fi, 1),
        "perimeter_growth_chains_hr": perimeter_chains_hr,
        "recommended_resources": recommended,
    }


@tool
def compare_resources_to_needs(cluster_id: str | None = None) -> dict[str, Any]:
    """Compare available resources against estimated needs for the current fire.

    Combines fire behavior assessment with resource inventory to produce
    a gap analysis: what we have vs. what we need.

    Args:
        cluster_id: Optional cluster to scope the inventory check.
                    None checks all clusters.

    Returns:
        Dict with:
          - adequate          : bool — are current resources sufficient?
          - suppression_difficulty: category for current intensity
          - available         : dict of resource types → count on hand
          - needed            : dict of resource types → count required
          - gaps              : list of shortfall descriptions
          - surplus           : list of excess resource descriptions
    """
    fb = _get_fire_behavior()
    if fb is None:
        return {"error": "No fire behavior data available", "adequate": False}

    inventory = _get_resource_inventory()

    max_fi = fb.get("max_fireline_intensity", 0.0)
    cat = suppression_category(max_fi)

    # Get available resources.
    if inventory is not None:
        if cluster_id is not None:
            resources = inventory.by_cluster(cluster_id)
        else:
            resources = inventory.all_resources()
        from resources.base import ResourceStatus
        available_resources = [r for r in resources if r.status == ResourceStatus.AVAILABLE]
        available_by_type: dict[str, int] = {}
        for r in available_resources:
            available_by_type[r.resource_type] = available_by_type.get(r.resource_type, 0) + 1
    else:
        available_by_type = {}

    # Determine needed resources based on suppression category.
    needed_by_type: dict[str, int] = {}
    if cat in ("hand_crew",):
        needed_by_type["crew"] = 2
        needed_by_type["engine"] = 2
    elif cat == "engine":
        needed_by_type["engine"] = 2
        needed_by_type["crew"] = 1
    elif cat == "dozer":
        needed_by_type["dozer"] = 1
        needed_by_type["engine"] = 2
    elif cat == "aerial_only":
        needed_by_type["helicopter"] = 1
        needed_by_type["dozer"] = 2
    else:  # beyond_suppression
        needed_by_type["helicopter"] = 2

    # Compute gaps and surplus.
    gaps: list[str] = []
    surplus: list[str] = []
    all_types = set(needed_by_type) | set(available_by_type)

    for rtype in sorted(all_types):
        have = available_by_type.get(rtype, 0)
        need = needed_by_type.get(rtype, 0)
        if need > 0 and have < need:
            gaps.append(
                f"{rtype}: need {need}, have {have} "
                f"(shortage of {need - have})"
            )
        elif have > need and need > 0:
            surplus.append(f"{rtype}: have {have}, need {need} (excess {have - need})")
        elif have > 0 and need == 0:
            surplus.append(f"{rtype}: {have} available (not needed for {cat})")

    # Intensity-based additional checks.
    if max_fi > INTENSITY_THRESHOLDS["hand_crew"] and available_by_type.get("crew", 0) > 0:
        if "crew" not in needed_by_type:
            gaps.append(
                f"Fireline intensity {max_fi:.0f} BTU/ft/s exceeds hand-crew "
                "safe engagement limit — redeploy crews to indirect attack"
            )
    if max_fi > INTENSITY_THRESHOLDS["engine"] and available_by_type.get("engine", 0) > 0:
        if "engine" not in needed_by_type:
            gaps.append(
                f"Fireline intensity {max_fi:.0f} BTU/ft/s — engines marginal "
                "for direct attack; consider aerial resources"
            )

    adequate = len(gaps) == 0

    return {
        "adequate": adequate,
        "suppression_difficulty": cat,
        "max_fireline_intensity": round(max_fi, 1),
        "available": available_by_type,
        "needed": needed_by_type,
        "gaps": gaps,
        "surplus": surplus,
    }


# ── Tool list for binding ────────────────────────────────────────────────────

FIRE_BEHAVIOR_TOOLS = [
    get_fire_behavior,
    get_resource_needs,
    compare_resources_to_needs,
]
