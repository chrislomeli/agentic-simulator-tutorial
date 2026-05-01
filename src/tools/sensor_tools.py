"""
ogar.tools.sensor_tools

LangGraph tools that the cluster agent LLM calls during classification.

These tools give the LLM structured access to sensor data so it can
reason about anomalies.  Each tool reads from the agent's state
(passed via the tool's context) and returns structured data.

Tools
─────
  get_recent_readings    : Return the last N sensor events in the window.
  get_sensor_summary     : Aggregate stats (min, max, mean) per sensor type.
  check_threshold        : Test whether a specific reading exceeds a threshold.
  get_cluster_status     : Return metadata about the cluster and event count.

Design notes
────────────
  - Tools are plain functions decorated with @tool.
  - They accept simple arguments (strings, numbers) so the LLM can call them.
  - They read from a shared state store rather than taking the full state.
    In LangGraph, the ToolNode invokes tools and merges results back as messages.
  - All tools return JSON-serializable dicts, which the LLM sees as tool results.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from transport.schemas import SensorEvent

# ── State store ──────────────────────────────────────────────────────────────
# Tools need access to the current sensor events.  We use a simple module-level
# holder that the graph sets before invoking tools.  This avoids passing the
# full LangGraph state into each tool function.

class _SensorToolState:
    """Mutable holder for the current cluster's sensor events."""
    events: list[SensorEvent] = []
    cluster_id: str = ""


_state = _SensorToolState()


def set_tool_state(events: list[SensorEvent], cluster_id: str) -> None:
    """Called by the graph before the LLM/tool loop to load context."""
    _state.events = list(events)
    _state.cluster_id = cluster_id


def clear_tool_state() -> None:
    """Called after the loop to clean up."""
    _state.events = []
    _state.cluster_id = ""


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def get_recent_readings(
    source_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most recent sensor readings from this cluster.

    Args:
        source_type: Filter by sensor type (e.g. "temperature", "smoke").
                     If None, return all types.
        limit: Maximum number of readings to return (default 10).

    Returns:
        List of dicts with source_id, source_type, sim_tick, confidence,
        and payload for each reading.
    """
    events = _state.events
    if source_type:
        events = [e for e in events if e.source_type == source_type]
    events = events[-limit:]
    return [
        {
            "source_id": e.source_id,
            "source_type": e.source_type,
            "sim_tick": e.sim_tick,
            "confidence": e.confidence,
            "payload": e.payload,
        }
        for e in events
    ]


@tool
def get_sensor_summary() -> dict[str, Any]:
    """Compute aggregate statistics per sensor type in the current window.

    Returns:
        Dict mapping each source_type to:
          - count: number of readings
          - source_ids: unique sensor IDs
          - min_confidence: lowest confidence score
          - avg_confidence: mean confidence score
          - latest_payload: the most recent reading's payload
    """
    events = _state.events
    by_type: dict[str, list[SensorEvent]] = {}
    for e in events:
        by_type.setdefault(e.source_type, []).append(e)

    summary = {}
    for stype, evts in by_type.items():
        confs = [e.confidence for e in evts]
        summary[stype] = {
            "count": len(evts),
            "source_ids": list({e.source_id for e in evts}),
            "min_confidence": min(confs),
            "avg_confidence": round(sum(confs) / len(confs), 3),
            "latest_payload": evts[-1].payload,
        }
    return summary


@tool
def check_threshold(
    source_type: str,
    payload_key: str,
    threshold: float,
    direction: str = "above",
) -> dict[str, Any]:
    """Check if any sensor reading exceeds (or falls below) a threshold.

    Args:
        source_type: The sensor type to check (e.g. "temperature").
        payload_key: The key inside the payload dict (e.g. "celsius").
        threshold: The numeric threshold value.
        direction: "above" to check for values > threshold,
                   "below" to check for values < threshold.

    Returns:
        Dict with:
          - breached: True if any reading crosses the threshold
          - breach_count: how many readings crossed
          - max_value / min_value: extremes found
          - readings: list of breaching readings with source_id and value
    """
    events = [e for e in _state.events if e.source_type == source_type]
    values = []
    breaches = []
    for e in events:
        val = e.payload.get(payload_key)
        if val is None:
            continue
        values.append(val)
        if direction == "above" and val > threshold:
            breaches.append({"source_id": e.source_id, "sim_tick": e.sim_tick, "value": val})
        elif direction == "below" and val < threshold:
            breaches.append({"source_id": e.source_id, "sim_tick": e.sim_tick, "value": val})

    return {
        "breached": len(breaches) > 0,
        "breach_count": len(breaches),
        "total_readings": len(values),
        "max_value": max(values) if values else None,
        "min_value": min(values) if values else None,
        "readings": breaches[-5:],  # cap at 5 to avoid huge tool results
    }


@tool
def get_cluster_status() -> dict[str, Any]:
    """Return metadata about the current cluster and its event window.

    Returns:
        Dict with cluster_id, total_events, unique_sensors, unique_types,
        tick_range (earliest to latest sim_tick in the window).
    """
    events = _state.events
    ticks = [e.sim_tick for e in events] if events else []
    return {
        "cluster_id": _state.cluster_id,
        "total_events": len(events),
        "unique_sensors": len({e.source_id for e in events}),
        "unique_types": list({e.source_type for e in events}),
        "tick_range": [min(ticks), max(ticks)] if ticks else [],
    }


# ── Tool list for binding ────────────────────────────────────────────────────

SENSOR_TOOLS = [
    get_recent_readings,
    get_sensor_summary,
    check_threshold,
    get_cluster_status,
]
