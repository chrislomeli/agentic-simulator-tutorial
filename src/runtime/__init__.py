"""
runtime — the simulator's runtime loop.

This package owns the long-running components that turn a loaded
world into a stream of LLM evaluations:

  * SensorPublisher  — ticks the engine and samples sensors.
  * CellStateManager — tracks per-cell state, emits triggered
                       positions when evaluation thresholds are crossed.
  * RuntimeOrchestrator — wires the two together and dispatches
                          micro-batches (CellReadings) into the supervisor
                          graph.

The orchestrator is *not* a graph node; it sits outside the graph,
treating compiled graphs as pure-compute callables. This keeps the
graphs unaware of timing, queues, and lifecycle.
"""

from __future__ import annotations

from runtime.orchestrator import RuntimeOrchestrator, RuntimeStats

__all__ = ["RuntimeOrchestrator", "RuntimeStats"]
