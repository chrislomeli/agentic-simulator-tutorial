"""
ogar.bridge.consumer

Async event bridge consumer — reads SensorEvents from a queue
and dispatches them to cluster agent graphs.

Responsibility
──────────────
The consumer sits between the transport queue and the agent layer.
For each event it:
  1. Reads the event's cluster_id.
  2. Looks up (or creates) the compiled cluster agent graph for that cluster.
  3. Invokes the graph with the event as the trigger.
  4. Collects the resulting AnomalyFindings and stores them.

In a production system this would be a Kafka consumer group with
partition assignment by cluster_id.  Here it is a single async loop
reading from SensorEventQueue.

Why async?
──────────
Agent graph invocations may involve LLM calls (I/O-bound).
Running as an async consumer lets us process events without blocking
the publisher or other consumers.

Usage
─────
  consumer = EventBridgeConsumer(queue=queue, agent_graph=cluster_graph)
  task = asyncio.create_task(consumer.run())
  # ... later ...
  consumer.stop()
  await task
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from agents.cluster.state import AnomalyFinding
from transport.queue import SensorEventQueue
from transport.schemas import SensorEvent

logger = logging.getLogger(__name__)


class EventBridgeConsumer:
    """
    Async consumer that routes SensorEvents to cluster agent graphs.

    The consumer reads events one at a time from the queue, groups
    them by cluster_id, and invokes the cluster agent graph for each
    event.  Results (AnomalyFindings) are accumulated and can be
    retrieved via collected_findings.

    Parameters
    ──────────
    queue        : The SensorEventQueue to consume from.
    agent_graph  : A compiled LangGraph cluster agent graph.
                   Must accept ClusterAgentState and return it.
    on_finding   : Optional callback invoked for each AnomalyFinding.
                   Signature: (finding: AnomalyFinding) -> None
    batch_size   : How many events to accumulate per cluster before
                   invoking the graph.  Default 1 = invoke per event.
    """

    def __init__(
        self,
        *,
        queue: SensorEventQueue,
        agent_graph: Any,
        on_finding: Optional[Callable[[AnomalyFinding], None]] = None,
        batch_size: int = 1,
    ) -> None:
        self._queue = queue
        self._agent_graph = agent_graph
        self._on_finding = on_finding
        self._batch_size = max(1, batch_size)

        # Per-cluster event buffers for batching.
        self._buffers: Dict[str, List[SensorEvent]] = {}

        # All findings collected across all invocations.
        self.collected_findings: List[AnomalyFinding] = []

        # Total events consumed.
        self.events_consumed: int = 0

        # Total graph invocations.
        self.invocations: int = 0

        self._stop_requested: bool = False

    def stop(self) -> None:
        """Signal the consumer to stop after finishing the current event."""
        logger.info("EventBridgeConsumer stop requested")
        self._stop_requested = True

    async def run(self, max_events: Optional[int] = None) -> None:
        """
        Run the consumer loop.

        Parameters
        ──────────
        max_events : If provided, stop after consuming this many events.
                     If None, run until stop() is called or the task is cancelled.
        """
        self._stop_requested = False
        self.events_consumed = 0
        self.invocations = 0
        self.collected_findings = []
        self._buffers = {}

        logger.info(
            "EventBridgeConsumer starting — batch_size=%d, limit=%s",
            self._batch_size,
            max_events if max_events is not None else "∞",
        )

        while True:
            if self._stop_requested:
                logger.info(
                    "EventBridgeConsumer stopped after %d events, %d invocations",
                    self.events_consumed,
                    self.invocations,
                )
                break

            if max_events is not None and self.events_consumed >= max_events:
                logger.info(
                    "EventBridgeConsumer reached event limit (%d)",
                    max_events,
                )
                break

            # Read one event from the queue.
            # Use wait_for with a short timeout so we can check stop conditions.
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            self.events_consumed += 1
            cluster_id = event.cluster_id

            logger.debug(
                "Consumed event %s from %s (cluster=%s, tick=%d)",
                event.event_id,
                event.source_id,
                cluster_id,
                event.sim_tick,
            )

            # Buffer events per cluster for batching.
            if cluster_id not in self._buffers:
                self._buffers[cluster_id] = []
            self._buffers[cluster_id].append(event)

            # Invoke the graph when the batch is full.
            if len(self._buffers[cluster_id]) >= self._batch_size:
                await self._invoke_agent(cluster_id)

            self._queue.task_done()

        # Flush any remaining partial batches.
        for cluster_id in list(self._buffers.keys()):
            if self._buffers[cluster_id]:
                await self._invoke_agent(cluster_id)

    async def _invoke_agent(self, cluster_id: str) -> None:
        """Invoke the cluster agent graph with buffered events."""
        events = self._buffers.pop(cluster_id, [])
        if not events:
            return

        trigger = events[-1]  # Most recent event is the trigger.

        state = {
            "cluster_id": cluster_id,
            "workflow_id": f"{cluster_id}::bridge-{self.invocations}",
            "sensor_events": events,
            "trigger_event": trigger,
            "messages": [],
            "anomalies": [],
            "status": "idle",
            "error_message": None,
        }

        logger.info(
            "Invoking cluster agent for %s with %d event(s)",
            cluster_id,
            len(events),
        )

        try:
            result = self._agent_graph.invoke(state)
            self.invocations += 1

            findings = result.get("anomalies", [])
            for finding in findings:
                self.collected_findings.append(finding)
                if self._on_finding:
                    self._on_finding(finding)

            logger.info(
                "Cluster agent %s returned %d finding(s), status=%s",
                cluster_id,
                len(findings),
                result.get("status"),
            )

        except Exception:
            logger.exception(
                "Error invoking cluster agent for %s",
                cluster_id,
            )
