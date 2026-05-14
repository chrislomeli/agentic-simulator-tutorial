"""
world-simulator.agents.commons

Public API surface for shared agent infrastructure.

This package provides cross-cutting concerns used by both the cluster agent
and the supervisor: state types, geo utilities, and shared data schemas.
Import from here rather than from submodules to stay resilient to internal
reorganization.

Quick reference:
  - StatusValue        → state machine enum (idle, processing, completed, error)
  - TracedState        → base state class with session_id, status, error
  - GridPosition       → (row, col) coordinate
  - Metric             → sensor reading with signal strength
  - CellReadings       → triggered cell envelope (cluster_id + position + metrics)
  - CollatedRecordRisk → risk assessment for a single cell
  - RiskAssessment     → container for all risk assessments
  - LatLon             → real-world coordinate
  - cell_size_miles    → calculate cell dimensions
  - grid_to_latlon     → convert grid (row, col) → real coordinate
  - latlon_to_grid     → convert real coordinate → grid (row, col)
"""

# Layer 1: state_types (no dependencies)
# Layer 2: geo (no internal dependencies)
# AgentDependencies imports the world layer (CellStateManager) for trend
# access — importing it here would cycle via world.cell_state_manager →
# agents.commons.schemas → agents/commons/__init__.py. Consumers should
# import AgentDependencies directly from agents.commons.agent_dependencies.
from agents.commons.geo import LatLon, cell_size_miles, grid_to_latlon, latlon_to_grid


# Layer 3: schemas (depends on state_types)
from agents.commons.schemas import (
    CellReadings,
    CollatedRecordRisk,
    GridPosition,
    Metric,
    RiskAssessment,
    TracedState,
)
from agents.commons.state_types import StatusValue

__all__ = [
    # state_types
    "StatusValue",
    # geo
    "LatLon",
    "cell_size_miles",
    "grid_to_latlon",
    "latlon_to_grid",
    # schemas
    "TracedState",
    "GridPosition",
    "Metric",
    "CellReadings",
    "CollatedRecordRisk",
    "RiskAssessment",
]
