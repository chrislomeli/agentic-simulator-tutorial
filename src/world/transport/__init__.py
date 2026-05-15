"""
world-simiulator.transport

Everything related to moving events between components.

  schemas.py  ← The SensorEvent envelope — the single shared contract
                between sensors, the bridge consumer, and agents.
  queue.py    ← Async event queue decoupling producers from consumers.

Nothing in this package knows about LangGraph, sensors, or actuators.
It is pure data contract + naming conventions.
"""

from world.transport.queue import SensorEventQueue as SensorEventQueue
from world.transport.schemas import SensorEvent as SensorEvent

__all__ = [
    "SensorEventQueue",
    "SensorEvent",
]
