"""main.py — local entrypoint: a real entry point to the graph.

Demonstrates the deployment-agnostic path:

    list of changed cells ──► GraphClient.invoke ──► GraphFacade
                                                       │ reads the world map
                                                       ▼
                                       supervisor graph (world injected)

The CQRS write side (sensors → world update) is *simulated* briefly here
to produce realistic world state plus the list of changed cells; in a
real deployment that is the upstream consumer's job, on its own
deployable. This file then exercises the actual entry point: build a
TriggerRequest from those cells, call it through the in-process
GraphClient adapter, print the TriggerResult.

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

from agents.commons.schemas import GridPosition  # noqa: E402
from runtime.composition import build_agent_dependencies, build_supervisor  # noqa: E402
from runtime.contract import TriggerRequest  # noqa: E402
from runtime.facade import GraphFacade  # noqa: E402
from runtime.graph_client import GraphClient, InProcessGraphClient  # noqa: E402
from stores import get_postgres_data_store  # noqa: E402
from world.cell_state_manager import CellStateManager  # noqa: E402
from world.domains.wildfire.sampler import sample_local_conditions  # noqa: E402
from world.domains.wildfire.scenario_loader import load_scenario_from_db  # noqa: E402


def simulate_write_side(engine, sensor_inventory, cell_state_manager) -> list[GridPosition]:
    """Stand in for the upstream CQRS consumer.

    Advances the world one tick, feeds each sensor's reading into the
    world (CellStateManager), and returns the cells that changed. In a
    real deployment this is a separate consumer that commits the world
    update *before* the trigger is sent; here it just produces realistic
    state plus the trigger the entry point will consume.
    """
    engine.tick()
    changed: set[tuple[int, int]] = set()
    for sensor in sensor_inventory.all_sensors():
        if sensor.grid_row is None or sensor.grid_col is None:
            continue
        conditions = sample_local_conditions(engine, sensor.grid_row, sensor.grid_col)
        event = sensor.emit(conditions)
        if event is None:
            continue
        for _cluster_id, row, col in cell_state_manager.update(event):
            changed.add((row, col))
    return [GridPosition(row=r, col=c) for r, c in sorted(changed)]


async def run_entrypoint(client: GraphClient, cells: list[GridPosition]) -> None:
    """The actual entry point: a trigger (list of cells) → the graph."""
    request = TriggerRequest(correlation_id=str(uuid.uuid4()), cells=cells)

    print()
    print(f"=== Invoking graph for trigger {request.correlation_id} ===")
    print(f"  changed cells: {len(cells)}")
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
    data_store = get_postgres_data_store()
    try:
        engine, sensor_inventory = load_scenario_from_db("lpnf-south", data_store)
        cell_state_manager = CellStateManager(
            world_grid=engine.grid,
            sensor_inventory=sensor_inventory,
        )
        agent_deps = build_agent_dependencies(engine, cell_state_manager, data_store=data_store)
        supervisor_graph = build_supervisor(agent_deps)

        # Built once (startup phase): the directly-callable service and
        # the in-process binding of the outbound port.
        facade = GraphFacade(
            supervisor_graph=supervisor_graph,
            cell_state_manager=cell_state_manager,
        )
        client: GraphClient = InProcessGraphClient(facade)

        # Upstream write side (simulated): commit world state, get the
        # changed cells. In production this is a separate deployable.
        changed_cells = simulate_write_side(engine, sensor_inventory, cell_state_manager)

        # The real entry point: trigger → graph, via the port.
        asyncio.run(run_entrypoint(client, changed_cells))
    finally:
        data_store.close()


if __name__ == "__main__":
    main()
