"""main.py — local entrypoint: a real entry point to the graph.

Demonstrates the deployment-agnostic path:

    batch of sensor events ──► GraphClient.invoke ──► GraphFacade
                                                        │ folds events onto
                                                        │ the immutable seed
                                                        ▼
                                        supervisor graph (world injected)

The producer (sensors → events) is *simulated* briefly here to generate
one tick of realistic events; in a real deployment that is the upstream
producer's job, on its own deployable. This file then exercises the
actual entry point: build a TriggerRequest carrying those events, call
it through the in-process GraphClient adapter, print the TriggerResult.
The facade — not this file — folds the events onto its seed-hydrated
world, so the DB seed stays immutable and the scenario replays.

The streaming RuntimeOrchestrator still exists in ``runtime/`` but is no
longer the entry path — the facade/port is.

Run from the project root::

    python main.py
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from logging_config import configure_logging

# configure_logging() must come before all project imports so that
# module-level loggers are captured by structlog from the first record.
configure_logging(level=logging.INFO)

from config import get_settings  # noqa: E402
from runtime.contract import GraphClient, TriggerRequest  # noqa: E402
from runtime.profiles import build_runtime  # noqa: E402
from world.domains.wildfire.sampler import sample_local_conditions  # noqa: E402
from world.transport import SensorEvent  # noqa: E402


def simulate_write_side(engine, sensor_inventory) -> list[SensorEvent]:
    """Stand in for the upstream producer.

    Advances the world one tick and emits each sensor's reading as a
    SensorEvent. It does NOT fold them into world state — that is the
    graph side's job (the facade folds onto its immutable seed). In a
    real deployment this is a separate producer on its own deployable;
    here it just generates one tick of realistic events for the trigger.
    """
    engine.tick()
    events: list[SensorEvent] = []
    for sensor in sensor_inventory.all_sensors():
        if sensor.grid_row is None or sensor.grid_col is None:
            continue
        conditions = sample_local_conditions(engine, sensor.grid_row, sensor.grid_col)
        event = sensor.emit(conditions)
        if event is None:
            continue
        events.append(event)
    return events


async def run_entrypoint(client: GraphClient, events: list[SensorEvent]) -> None:
    """The actual entry point: a trigger (batch of events) → the graph."""
    request = TriggerRequest(correlation_id=str(uuid.uuid4()), events=events)

    print()
    print(f"=== Invoking graph for trigger {request.correlation_id} ===")
    print(f"  sensor events: {len(events)}")
    result = await client.invoke(request)

    print()
    print("=== Result ===")
    print(f"  correlation_id:           {result.correlation_id}")
    print(f"  clusters processed:       {len(result.cluster_ids)}")
    print(f"  RiskAssessments produced: {result.assessments_produced}")
    if result.cluster_score:
        print("  Cluster risk scores (0–10):")
        for cluster, score in sorted(result.cluster_score.items()):
            print(f"    {cluster:24s}  score: {score.risk_score:2d},  confidence: {score.confidence:2d}")


def main() -> None:
    # One lever. ``build_runtime`` reads ``deployment_profile`` and binds
    # the store/queue/graph-client adapters for that target. main.py owns
    # no wiring — only the (simulated) upstream write side and the entry
    # point, both deployment-agnostic.
    settings = get_settings()
    bundle = build_runtime(settings)
    print(f"=== deployment profile: {bundle.profile.value} ===")

    client: GraphClient = bundle.graph_client
    try:
        # Upstream producer (simulated): one tick of sensor events. In
        # production this is a separate deployable; it does not fold
        # state — the facade behind the port does, onto the seed.
        events = simulate_write_side(bundle.engine, bundle.sensor_inventory)

        # The real entry point: trigger → graph, via the port.
        asyncio.run(run_entrypoint(client, events))
    finally:
        bundle.close()


if __name__ == "__main__":
    main()
