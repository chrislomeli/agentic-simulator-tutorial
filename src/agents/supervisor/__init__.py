"""
world-simulator.agents.supervisor

Public API for the supervisor agent — orchestrates parallel cluster analysis.

The supervisor receives batched events grouped by cluster, fans out to cluster
agents via LangGraph's Send API (parallel execution), waits for all results
(synchronization barrier), then assesses the overall situation and dispatches
actuator commands.

Quick reference:
  - SupervisorState        → Pydantic state schema with aggregate_findings reducer
  - ActuatorCommand        → Stub command structure for dispatch node
  - build_supervisor_graph → Factory that compiles the orchestration graph
"""

from agents.supervisor.graph import build_supervisor_graph
from agents.supervisor.state import ActuatorCommand, SupervisorState

__all__ = [
    "ActuatorCommand",
    "SupervisorState",
    "build_supervisor_graph",
]
