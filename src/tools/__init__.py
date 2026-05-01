"""
ogar.tools

LangGraph tools that agents can invoke via ToolNode.

Tool lists (pass directly to ToolNode or bind_tools):
  SENSOR_TOOLS         — query recent sensor readings for a cluster
  RESOURCE_TOOLS       — query resource inventory and preparedness
  FIRE_BEHAVIOR_TOOLS  — fire behavior metrics and resource needs
  SUPERVISOR_TOOLS     — cross-cluster findings and anomaly summaries

State management (call before running an agent graph):
  set_tool_state / clear_tool_state            — sensor tools
  set_resource_tool_state / clear_...          — resource tools
  set_fire_behavior_tool_state / clear_...     — fire behavior tools
  set_supervisor_tool_state / clear_...        — supervisor tools
"""

from tools.fire_behavior_tools import FIRE_BEHAVIOR_TOOLS as FIRE_BEHAVIOR_TOOLS
from tools.fire_behavior_tools import (
    clear_fire_behavior_tool_state as clear_fire_behavior_tool_state,
)
from tools.fire_behavior_tools import set_fire_behavior_tool_state as set_fire_behavior_tool_state
from tools.resource_tools import RESOURCE_TOOLS as RESOURCE_TOOLS
from tools.resource_tools import clear_resource_tool_state as clear_resource_tool_state
from tools.resource_tools import set_resource_tool_state as set_resource_tool_state
from tools.sensor_tools import SENSOR_TOOLS as SENSOR_TOOLS
from tools.sensor_tools import clear_tool_state as clear_tool_state
from tools.sensor_tools import set_tool_state as set_tool_state
from tools.supervisor_tools import SUPERVISOR_TOOLS as SUPERVISOR_TOOLS
from tools.supervisor_tools import clear_supervisor_tool_state as clear_supervisor_tool_state
from tools.supervisor_tools import set_supervisor_tool_state as set_supervisor_tool_state

__all__ = [
    # Tool lists
    "SENSOR_TOOLS",
    "RESOURCE_TOOLS",
    "FIRE_BEHAVIOR_TOOLS",
    "SUPERVISOR_TOOLS",
    # State management
    "set_tool_state",
    "clear_tool_state",
    "set_resource_tool_state",
    "clear_resource_tool_state",
    "set_fire_behavior_tool_state",
    "clear_fire_behavior_tool_state",
    "set_supervisor_tool_state",
    "clear_supervisor_tool_state",
]
