"""
ogar.tools.supervisor_tools

LangGraph tools that the supervisor LLM calls during situation assessment
and action decision-making.

These tools give the LLM structured access to aggregated findings from
cluster agents, so it can reason about cross-cluster patterns and decide
what actuator commands to issue.

Tools
─────
  get_all_findings       : Return all cluster findings in the current window.
  get_findings_by_cluster: Filter findings for a specific cluster.
  get_finding_summary    : Aggregate stats across all findings (counts, types).
  check_cross_cluster    : Detect correlated anomalies across multiple clusters.

Design notes
────────────
  - Same module-level state holder pattern as sensor_tools.py.
  - The supervisor graph calls set_supervisor_tool_state() before the LLM
    loop, loading findings and cluster IDs into the holder.
  - Tools return JSON-serializable dicts so the LLM sees them as tool results.
  - The supervisor uses these in two phases:
      1. assess_situation — LLM calls tools to understand what happened
      2. decide_actions  — LLM calls tools to decide what commands to issue
    Both phases share the same tool state for a given supervisor execution.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from langchain_core.tools import tool

from agents.cluster.state import AnomalyFinding
from resources.inventory import ResourceInventory

# ── State store ──────────────────────────────────────────────────────────────
# Same pattern as sensor_tools.py — a module-level mutable holder that the
# graph sets before invoking the LLM/tool loop.

class _SupervisorToolState:
    """Mutable holder for the current supervisor execution's findings."""
    findings: list[AnomalyFinding] = []
    active_cluster_ids: list[str] = []
    resource_inventory: ResourceInventory | None = None
    fire_behavior_summary: dict[str, Any] | None = None


_state = _SupervisorToolState()


def set_supervisor_tool_state(
    findings: list[AnomalyFinding],
    active_cluster_ids: list[str],
    resource_inventory: ResourceInventory | None = None,
    fire_behavior_summary: dict[str, Any] | None = None,
) -> None:
    """Called by the graph before the LLM/tool loop to load context."""
    _state.findings = list(findings)
    _state.active_cluster_ids = list(active_cluster_ids)
    _state.resource_inventory = resource_inventory
    _state.fire_behavior_summary = fire_behavior_summary


def clear_supervisor_tool_state() -> None:
    """Called after the loop to clean up."""
    _state.findings = []
    _state.active_cluster_ids = []
    _state.resource_inventory = None
    _state.fire_behavior_summary = None


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def get_all_findings(limit: int = 50) -> list[dict[str, Any]]:
    """Return all cluster findings from the current supervisor execution.

    Args:
        limit: Maximum number of findings to return (default 50).

    Returns:
        List of finding dicts with finding_id, cluster_id, anomaly_type,
        affected_sensors, confidence, and summary.
    """
    findings = _state.findings[:limit]
    return [
        {
            "finding_id": f["finding_id"],
            "cluster_id": f["cluster_id"],
            "anomaly_type": f["anomaly_type"],
            "affected_sensors": f["affected_sensors"],
            "confidence": f["confidence"],
            "summary": f["summary"],
        }
        for f in findings
    ]


@tool
def get_findings_by_cluster(cluster_id: str) -> list[dict[str, Any]]:
    """Return findings for a specific cluster.

    Args:
        cluster_id: The cluster to filter by (e.g. "cluster-north").

    Returns:
        List of finding dicts for that cluster.
    """
    findings = [f for f in _state.findings if f["cluster_id"] == cluster_id]
    return [
        {
            "finding_id": f["finding_id"],
            "cluster_id": f["cluster_id"],
            "anomaly_type": f["anomaly_type"],
            "affected_sensors": f["affected_sensors"],
            "confidence": f["confidence"],
            "summary": f["summary"],
        }
        for f in findings
    ]


@tool
def get_finding_summary() -> dict[str, Any]:
    """Compute aggregate statistics across all cluster findings.

    Returns:
        Dict with:
          - total_findings: total count
          - by_cluster: dict mapping cluster_id to finding count
          - by_type: dict mapping anomaly_type to finding count
          - avg_confidence: mean confidence across all findings
          - high_confidence_count: findings with confidence >= 0.7
          - affected_clusters: list of cluster IDs with findings
    """
    findings = _state.findings
    if not findings:
        return {
            "total_findings": 0,
            "by_cluster": {},
            "by_type": {},
            "avg_confidence": 0.0,
            "high_confidence_count": 0,
            "affected_clusters": [],
        }

    by_cluster = Counter(f["cluster_id"] for f in findings)
    by_type = Counter(f["anomaly_type"] for f in findings)
    confs = [f["confidence"] for f in findings]

    return {
        "total_findings": len(findings),
        "by_cluster": dict(by_cluster),
        "by_type": dict(by_type),
        "avg_confidence": round(sum(confs) / len(confs), 3),
        "high_confidence_count": sum(1 for c in confs if c >= 0.7),
        "affected_clusters": list(by_cluster.keys()),
    }


@tool
def check_cross_cluster(anomaly_type: str | None = None) -> dict[str, Any]:
    """Detect correlated anomalies across multiple clusters.

    Looks for the same anomaly_type appearing in multiple clusters,
    which may indicate a large-scale event (e.g. a fire front crossing
    cluster boundaries).

    Args:
        anomaly_type: If provided, only check for this specific type.
                      If None, check all types.

    Returns:
        Dict with:
          - correlated: True if the same anomaly type appears in 2+ clusters
          - correlations: list of dicts with anomaly_type, clusters, count
    """
    findings = _state.findings
    if anomaly_type:
        findings = [f for f in findings if f["anomaly_type"] == anomaly_type]

    # Group by anomaly_type → set of cluster_ids
    type_to_clusters: dict[str, set] = {}
    for f in findings:
        type_to_clusters.setdefault(f["anomaly_type"], set()).add(f["cluster_id"])

    correlations = []
    for atype, clusters in type_to_clusters.items():
        if len(clusters) >= 2:
            correlations.append({
                "anomaly_type": atype,
                "clusters": sorted(clusters),
                "cluster_count": len(clusters),
            })

    return {
        "correlated": len(correlations) > 0,
        "correlations": correlations,
        "total_clusters_checked": len(_state.active_cluster_ids),
    }


# ── Tool list for binding ────────────────────────────────────────────────────

SUPERVISOR_TOOLS = [
    get_all_findings,
    get_findings_by_cluster,
    get_finding_summary,
    check_cross_cluster,
]
