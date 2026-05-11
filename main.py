"""
main.py — load the real-world Los Padres scenario and run the streaming
runtime orchestrator end-to-end.

Pipeline:

    scenario_loader  ──► engine + sensor_inventory
                                │
                                ▼
                        RuntimeOrchestrator
                          │   │   │
                          │   │   └── SupervisorGraph
                          │   │         (fans out to cluster agents,
                          │   │          aggregates cluster_score)
                          │   └────── CellStateManager (collator)
                          └────────── SensorPublisher (drives engine.tick)

The composition root: wires LLM registry, prompt registry, and the
supervisor graph (which compiles its child cluster graph internally),
then hands everything to the RuntimeOrchestrator.

Run from the project root::

    python main.py
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from agents.commons.agent_dependencies import AgentDependencies
from agents.commons.geo import cell_size_miles
from agents.commons.schemas import GridPosition, Metric, CollatedRecord, TerrainContext, CoverageSummary, TimeWindow
from agents.supervisor.graph import build_supervisor_graph
from agents.supervisor.state import SupervisorGraph, SupervisorState
from logging_config import configure_logging
from prompts import PromptRegistry

# configure_logging() must come before all project imports so that
# module-level loggers are captured by structlog from the first record.
configure_logging(level=logging.INFO)


from agents.commons.schemas import CollatedRecord, RiskAssessment  # noqa: E402
from config import get_settings  # noqa: E402
from stores import get_pg_gateway  # noqa: E402
from agents.commons.llm_registry import LLMLabel, build_llm_registry, models
from domains.wildfire.sampler import sample_local_conditions  # noqa: E402
from domains.wildfire.scenario_loader import load_scenario_from_package  # noqa: E402
from domains.wildfire.world_builder.regions import get_region  # noqa: E402
from runtime import RuntimeOrchestrator  # noqa: E402

# Smoke-test cadence — fast enough that the demo finishes in a few
# seconds, slow enough that publisher and consumer can interleave.
SMOKE_TICKS = 1
SMOKE_TICK_INTERVAL_SEC = 0.05


def print_world_summary(engine, sensor_inventory, region) -> None:
    """One-shot summary of the loaded world before the loop starts."""
    rows, cols = engine.grid.rows, engine.grid.cols
    lat_mi, lon_mi = cell_size_miles(rows, cols, region.bounds)
    print()
    print(f"=== World loaded: {rows}x{cols} grid over {region.display_name} ===")
    print(f"  Cell size: ~{lat_mi:.2f} mi (lat) × {lon_mi:.2f} mi (lon)")

    sensors_by_cluster: dict[str, int] = {c: 0 for c in region.clusters}
    for sensor in sensor_inventory.all_sensors():
        sensors_by_cluster[sensor.cluster_id] = (
            sensors_by_cluster.get(sensor.cluster_id, 0) + 1
        )
    print(f"  Sensors:   {sum(sensors_by_cluster.values())} "
          f"(from {len(region.raws_stations)} RAWS stations × 3 types each)")
    for cluster, n in sensors_by_cluster.items():
        print(f"    {cluster:24s} {n:3d}")


def build_agent_deps() -> AgentDependencies:
    """Construct the LLM/prompt/store dependencies for graph compilation."""
    settings = get_settings()
    settings.apply_langsmith()

    llm_registry = build_llm_registry(settings, models, {
        "classifier": LLMLabel.GPT_MINI,
    })

    store = None

    prompt_registry = PromptRegistry()
    prompt_registry.register_models(CollatedRecord, RiskAssessment)

    return AgentDependencies(
        prompt_registry=prompt_registry,
        llm_registry=llm_registry,
        store=store,
    )


async def run_orchestrator(engine, sensor_inventory, agent_deps) -> None:
    """Build the supervisor graph, construct the orchestrator, run it."""
    supervisor_graph: SupervisorGraph = build_supervisor_graph(agent_dependencies=agent_deps)

    orchestrator = RuntimeOrchestrator(
        sensor_inventory=sensor_inventory,
        engine=engine,
        supervisor_graph=supervisor_graph,
        sampler=sample_local_conditions,
        tick_interval_seconds=SMOKE_TICK_INTERVAL_SEC,
    )

    print()
    print(f"=== Running orchestrator for {SMOKE_TICKS} tick(s) ===")
    stats = await orchestrator.run(ticks=SMOKE_TICKS)

    print()
    print("=== Run complete ===")
    print(f"  ticks completed:           {stats.ticks_completed}")
    print(f"  events consumed:           {stats.events_consumed}")
    print(f"  CollatedRecords emitted:   {stats.records_emitted}")
    print(f"  graph invocations:         {stats.graph_invocations}")
    for cluster, n in stats.invocations_by_cluster.items():
        print(f"    {cluster:24s}  invocations: {n:3d}")
    print(f"  RiskAssessments produced:  {stats.risk_assessments_produced}")
    if stats.cluster_score:
        print("  Cluster risk scores (0–10):")
        for cluster, score in sorted(stats.cluster_score.items()):
            print(f"    {cluster:24s}  score: {score.risk_score:2d},  confidence: {score.confidence:2d}")


def main() -> None:
    print("GET WORLD")
    region = get_region("lpnf-south")
    pg = get_pg_gateway()
    engine, sensor_inventory, risk_heat_map = load_scenario_from_package(pg, "lpnf-south")

    print_world_summary(engine, sensor_inventory, region)

    print("\n\nINVOKE GRAPH")
    agent_dependencies = build_agent_deps()
    asyncio.run(run_orchestrator(engine, sensor_inventory, risk_heat_map, agent_dependencies))


if __name__ == "__main__":
    main()
