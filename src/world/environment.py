"""
ogar.world.environment

Abstract base class for domain-specific environment states.

EnvironmentState
────────────────
The environment represents ambient conditions that affect the entire
grid uniformly (or at least are not per-cell).  For example:

  - A wildfire domain has temperature, humidity, wind speed/direction.
  - An ocean domain has current speed, wave height, salinity.
  - An epidemiological domain might have season, mobility_index.

The framework engine calls tick() once per simulation step to evolve
the environment.  It calls to_dict() when recording ground truth
snapshots.  The engine never interprets the contents — those are
the physics module's concern.

Why BaseModel + ABC
───────────────────
Using Pydantic BaseModel gives subclasses validation, serialisation,
and schema generation.  Using ABC enforces that every subclass
implements tick() and to_dict().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from pydantic import BaseModel


class EnvironmentState(BaseModel, ABC):
    """
    Abstract base for all domain-specific environment states.

    Subclasses MUST implement:
      tick()    — evolve the environment by one simulation step
      to_dict() — serialise for logging and ground truth snapshots

    Example
    ───────
      class FireEnvironmentState(EnvironmentState):
          temperature_c: float = 30.0
          humidity_pct: float = 25.0
          wind_speed_mps: float = 5.0

          def tick(self) -> None:
              self.temperature_c += random.uniform(-0.5, 0.5)

          def to_dict(self) -> dict:
              return {"temperature_c": self.temperature_c, ...}
    """

    # Pydantic v2 configuration — allow mutation so tick() can update fields
    model_config = {"arbitrary_types_allowed": True}

    @abstractmethod
    def tick(self) -> None:
        """
        Evolve the environment by one simulation step.

        Called by the engine at the start of each tick, before
        the physics module runs.  Implementations should update
        their fields in place.
        """
        ...

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise current state for logging and ground truth snapshots.

        The engine records this in every GroundTruthSnapshot so that
        post-scenario analysis can see what the environment looked
        like at each tick.
        """
        ...
