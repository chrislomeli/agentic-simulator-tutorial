"""
world-simulator.agents.logistics.tools

Tools the logistics LLM can call on demand. See README.md in this
directory for the design and the contract.

Public surface
──────────────
Each tool exports its input schema, output schema, and a
``make_<tool_name>`` factory. Build the tools at agent-graph
construction time and pass the list to ``llm.bind_tools([...])`` and
to ``langgraph.prebuilt.ToolNode([...])``.
"""

from agents.logistics.tools.resources import (
    GetResourcesWithinInput,
    GetResourcesWithinOutput,
    ReachableResource,
    make_get_resources_within,
)
from agents.logistics.tools.spread import (
    ProjectedBurnCell,
    SimulateSpreadFromInput,
    SimulateSpreadFromOutput,
    make_simulate_spread_from,
)
from agents.logistics.tools.wind_history import (
    GetWindHistoryInput,
    GetWindHistoryOutput,
    WindSample,
    make_get_wind_history,
)

__all__ = [
    # Factories — what graph.py calls
    "make_get_resources_within",
    "make_simulate_spread_from",
    "make_get_wind_history",
    # Input schemas
    "GetResourcesWithinInput",
    "SimulateSpreadFromInput",
    "GetWindHistoryInput",
    # Output schemas
    "GetResourcesWithinOutput",
    "SimulateSpreadFromOutput",
    "GetWindHistoryOutput",
    # Nested result types — re-exported for typing in the agent's code
    "ReachableResource",
    "ProjectedBurnCell",
    "WindSample",
]
