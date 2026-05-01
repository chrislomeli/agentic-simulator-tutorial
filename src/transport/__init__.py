"""
ogar.transport

Everything related to moving events between components.

  schemas.py  ← The SensorEvent envelope — the single shared contract
                between sensors, the bridge consumer, and agents.
  topics.py   ← Topic name constants and helpers.
  queue.py    ← Async event queue decoupling producers from consumers.

Nothing in this package knows about LangGraph, sensors, or actuators.
It is pure data contract + naming conventions.
"""

from transport.queue import SensorEventQueue as SensorEventQueue
from transport.schemas import SensorEvent as SensorEvent
from transport.topics import AGENTS_DECISIONS as AGENTS_DECISIONS
from transport.topics import COMMANDS_ACTUATORS as COMMANDS_ACTUATORS
from transport.topics import EVENTS_ANOMALY as EVENTS_ANOMALY
from transport.topics import RESULTS_ACTUATORS as RESULTS_ACTUATORS
from transport.topics import all_sensor_topic_pattern as all_sensor_topic_pattern
from transport.topics import sensor_topic as sensor_topic

__all__ = [
    "SensorEventQueue",
    "SensorEvent",
    "AGENTS_DECISIONS",
    "COMMANDS_ACTUATORS",
    "EVENTS_ANOMALY",
    "RESULTS_ACTUATORS",
    "all_sensor_topic_pattern",
    "sensor_topic",
]
