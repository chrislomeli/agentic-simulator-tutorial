"""
world-simiulator.transport

Everything related to moving events between components.

  schemas.py  ← The SensorEvent envelope — the single shared contract
                between sensors, the bridge consumer, and agents.
  port.py     ← EventQueue Protocol — the transport-agnostic seam.
  queue.py    ← In-process asyncio adapter (the local binding).
  broker.py   ← Networked adapter stub (k8s/aws profiles).

Nothing in this package knows about LangGraph, sensors, or actuators.
It is pure data contract + naming conventions.
"""

from world.transport.broker import BrokerEventQueue as BrokerEventQueue
from world.transport.port import EventQueue as EventQueue
from world.transport.queue import SensorEventQueue as SensorEventQueue
from world.transport.schemas import SensorEvent as SensorEvent

__all__ = [
    "EventQueue",
    "SensorEventQueue",
    "BrokerEventQueue",
    "SensorEvent",
]
