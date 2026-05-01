"""
ogar.tools.resource_tools

LangGraph tools that the supervisor LLM calls to query resource availability
and assess preparedness.

These tools give the LLM structured access to the ResourceInventory so it
can reason about whether the system is prepared to handle detected anomalies.

Tools
─────
  get_resource_summary     : Overall readiness: counts, capacity, availability by type.
  get_resources_by_cluster : What's available near a specific cluster.
  get_resources_by_type    : All resources of a type with status details.
  check_preparedness       : Is a specific cluster adequately covered?

Design notes
────────────
  - Same module-level state holder pattern as sensor_tools.py and supervisor_tools.py.
  - The supervisor graph calls set_resource_tool_state() before the LLM
    loop, loading the ResourceInventory into the holder.
  - Tools return JSON-serializable dicts so the LLM sees them as tool results.
  - The supervisor uses these during assess_situation and decide_actions
    to factor preparedness into its reasoning.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from resources.base import ResourceStatus
from resources.inventory import ResourceInventory

# ── State access ─────────────────────────────────────────────────────────────
# Resource tools read from the shared supervisor tool state.  The supervisor
# graph calls set_supervisor_tool_state(resource_inventory=...) before the
# LLM loop, which populates the inventory.  This avoids maintaining a
# separate state holder for resource tools.
#
# For standalone testing, set_resource_tool_state() and
# clear_resource_tool_state() are provided as convenience wrappers.

def _get_inventory() -> ResourceInventory | None:
    """Read the ResourceInventory from the supervisor tool state."""
    # Import here to avoid circular imports at module load time.
    # supervisor_tools imports from resources.inventory,
    # and resource_tools reads from supervisor_tools._state.
    from tools.supervisor_tools import _state as supervisor_state
    return supervisor_state.resource_inventory


def set_resource_tool_state(inventory: ResourceInventory) -> None:
    """Convenience wrapper for standalone testing — sets the inventory
    on the shared supervisor tool state."""
    from tools.supervisor_tools import _state as supervisor_state
    supervisor_state.resource_inventory = inventory


def clear_resource_tool_state() -> None:
    """Convenience wrapper for standalone testing — clears the inventory."""
    from tools.supervisor_tools import _state as supervisor_state
    supervisor_state.resource_inventory = None


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def get_resource_summary() -> dict[str, Any]:
    """Get an overall readiness summary of all resources.

    Returns:
        Dict with:
          - total_resources: total count
          - by_type: dict mapping resource_type to counts and capacity info
          - by_cluster: dict mapping cluster_id to resource counts
          - by_status: dict mapping status to count
    """
    inventory = _get_inventory()
    if inventory is None:
        return {"error": "No resource inventory available", "total_resources": 0}
    return inventory.readiness_summary()


@tool
def get_resources_by_cluster(cluster_id: str) -> list[dict[str, Any]]:
    """Get all resources assigned to a specific cluster.

    Args:
        cluster_id: The cluster to query (e.g. "cluster-north").

    Returns:
        List of resource summary dicts with resource_id, type, status,
        capacity, available, and location for each resource.
    """
    inventory = _get_inventory()
    if inventory is None:
        return []
    resources = inventory.by_cluster(cluster_id)
    return [r.to_summary_dict() for r in resources]


@tool
def get_resources_by_type(resource_type: str) -> list[dict[str, Any]]:
    """Get all resources of a specific type across all clusters.

    Args:
        resource_type: The type to query (e.g. "firetruck", "hospital").

    Returns:
        List of resource summary dicts for all resources of that type.
    """
    inventory = _get_inventory()
    if inventory is None:
        return []
    resources = inventory.by_type(resource_type)
    return [r.to_summary_dict() for r in resources]


@tool
def check_preparedness(cluster_id: str | None = None) -> dict[str, Any]:
    """Check whether a cluster (or the whole system) is adequately resourced.

    Examines resource availability and capacity to provide a preparedness
    assessment.  If cluster_id is provided, checks that cluster only.
    If None, checks all clusters.

    Args:
        cluster_id: Optional cluster to check. None checks all clusters.

    Returns:
        Dict with:
          - cluster_id: which cluster (or "all")
          - total_resources: count of resources in scope
          - available_resources: count with status AVAILABLE
          - resource_types_present: list of types available
          - total_capacity: sum of all capacity
          - available_capacity: sum of remaining capacity
          - utilization_pct: percentage of capacity in use
          - gaps: list of potential issues (e.g. "no medical resources")
    """
    inventory = _get_inventory()
    if inventory is None:
        return {"error": "No resource inventory available"}

    if cluster_id is not None:
        resources = inventory.by_cluster(cluster_id)
        scope = cluster_id
    else:
        resources = inventory.all_resources()
        scope = "all"

    if not resources:
        return {
            "cluster_id": scope,
            "total_resources": 0,
            "available_resources": 0,
            "resource_types_present": [],
            "total_capacity": 0.0,
            "available_capacity": 0.0,
            "utilization_pct": 0.0,
            "gaps": [f"No resources assigned to {scope}"],
        }

    available = [r for r in resources if r.status == ResourceStatus.AVAILABLE]
    types_present = sorted({r.resource_type for r in resources})
    total_cap = sum(r.capacity for r in resources)
    avail_cap = sum(r.available for r in resources)
    util_pct = round((1.0 - avail_cap / total_cap) * 100, 1) if total_cap > 0 else 0.0

    # Identify gaps — simple heuristic checks.
    gaps: list[str] = []
    if not available:
        gaps.append("No resources currently available (all deployed or out of service)")
    if avail_cap < total_cap * 0.2:
        gaps.append(f"Low capacity: only {avail_cap:.0f}/{total_cap:.0f} remaining ({util_pct:.0f}% utilized)")
    out_of_service = [r for r in resources if r.status == ResourceStatus.OUT_OF_SERVICE]
    if len(out_of_service) > len(resources) * 0.3:
        gaps.append(f"{len(out_of_service)}/{len(resources)} resources out of service")

    # ── Fire behavior-aware gap checks ───────────────────────────
    # When fire behavior data is available, cross-reference intensity
    # thresholds against the types present in this cluster/scope.
    from domains.wildfire.nwcg_resources import INTENSITY_THRESHOLDS
    from tools.supervisor_tools import _state as supervisor_state
    fire_behavior = supervisor_state.fire_behavior_summary
    if fire_behavior:
        intensity = fire_behavior.get("max_fireline_intensity", 0.0)
        if intensity > INTENSITY_THRESHOLDS["hand_crew"] and "crew" not in types_present:
            gaps.append(
                f"Fireline intensity {intensity:.0f} BTU/ft/s exceeds hand-crew "
                "threshold but no crews assigned to this scope"
            )
        if intensity > INTENSITY_THRESHOLDS["engine"] and "dozer" not in types_present:
            gaps.append(
                f"Fireline intensity {intensity:.0f} BTU/ft/s — dozers recommended "
                "but none assigned to this scope"
            )
        if intensity > INTENSITY_THRESHOLDS["dozer"]:
            aerial_types = {"helicopter", "air_tanker"}
            if not aerial_types.intersection(types_present):
                gaps.append(
                    f"Fireline intensity {intensity:.0f} BTU/ft/s — aerial resources "
                    "needed but none assigned to this scope"
                )

    return {
        "cluster_id": scope,
        "total_resources": len(resources),
        "available_resources": len(available),
        "resource_types_present": types_present,
        "total_capacity": total_cap,
        "available_capacity": avail_cap,
        "utilization_pct": util_pct,
        "gaps": gaps,
    }


# ── Tool list for binding ────────────────────────────────────────────────────

RESOURCE_TOOLS = [
    get_resource_summary,
    get_resources_by_cluster,
    get_resources_by_type,
    check_preparedness,
]
