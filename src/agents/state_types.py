"""
ogar.agents.state_types

Shared state primitives used by both the cluster agent and the supervisor.

Keeping these here prevents the supervisor from importing from the cluster
module (or vice versa) just to get a shared enum.
"""

from enum import StrEnum


class StatusValue(StrEnum):
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
