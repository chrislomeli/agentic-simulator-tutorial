"""
ogar.agents.schemas

Cross-agent data contracts.

Anything in this module is a contract between agents — written by one,
read by another. Promoting these out of any single agent's ``state.py``
keeps the agents from importing each other's internals (and avoids the
circular-import trap that follows).

Rule of thumb
─────────────
  - Lives only inside one graph?      → that graph's ``state.py``.
  - Used only by one node?            → that node's module.
  - Crosses agent boundaries?         → here.
  - Wire-format envelope?             → ``transport/schemas.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


# ── Cluster → Supervisor: anomaly findings ──────────────────────────────────

class AnomalyFinding(BaseModel):
    """
    A structured anomaly record produced by a cluster agent.

    Cluster agents write these; the supervisor reads them via the
    ``cluster_findings`` field on its own state. This is the
    canonical shape of "something a cluster noticed worth surfacing."

    finding_id      : UUID string. Stable across restarts.
    cluster_id      : Which cluster detected this.
    anomaly_type    : e.g. "sensor_fault", "threshold_breach", "correlated_event".
    affected_sensors: List of source_ids involved.
    confidence      : Agent's confidence this is a real event (not noise).
    summary         : Human-readable description for the supervisor's context.
    raw_context     : Relevant sensor readings that led to this finding.
                      Passed up so the supervisor can correlate across clusters.
    """
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_id: str
    anomaly_type: str
    affected_sensors: list[str] = Field(default_factory=list)
    confidence: float
    summary: str
    raw_context: dict[str, Any]
