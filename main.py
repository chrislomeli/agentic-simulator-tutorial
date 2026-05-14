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
import logging

from agents.commons.agent_dependencies import AgentDependencies
from agents.supervisor.graph import build_supervisor_graph
from agents.supervisor.state import SupervisorGraph
from logging_config import configure_logging
from prompts import PromptRegistry
from world import GenericWorldEngine

# configure_logging() must come before all project imports so that
# module-level loggers are captured by structlog from the first record.
configure_logging(level=logging.INFO)


from agents.commons.schemas import CellReadings, RiskAssessment, CollatedRecordRisk  # noqa: E402
from config import get_settings # noqa: E402
from stores import get_pg_gateway  # noqa: E402
from agents.commons.llm_registry import LLMLabel, build_llm_registry, models
from domains.wildfire.sampler import sample_local_conditions  # noqa: E402
from domains.wildfire.scenario_loader import load_scenario_from_db  # noqa: E402
from runtime import RuntimeOrchestrator  # noqa: E402
from world.cell_state_manager import CellStateManager  # noqa: E402

# Smoke-test cadence — fast enough that the demo finishes in a few
# seconds, slow enough that publisher and consumer can interleave.
SMOKE_TICKS = 1
SMOKE_TICK_INTERVAL_SEC = 0.05

def build_agent_deps(
    engine: GenericWorldEngine,
    cell_state_manager: CellStateManager,
    pg_gateway=None,
) -> AgentDependencies:
    """Construct the LLM/prompt/store dependencies for graph compilation."""
    settings = get_settings()
    settings.apply_langsmith()

    llm_registry = build_llm_registry(settings, models, {
        "classifier": LLMLabel.GPT_MINI,
        "logistics": LLMLabel.GPT_MINI,
    })

    store = None

    prompt_registry = PromptRegistry()
    prompt_registry.register_models(CellReadings, CollatedRecordRisk)

    return AgentDependencies(
        prompt_registry=prompt_registry,
        llm_registry=llm_registry,
        world_engine=engine,
        cell_state_manager=cell_state_manager,
        store=store,
        pg_gateway=pg_gateway,
    )


async def run_orchestrator(engine, sensor_inventory, cell_state_manager, agent_deps) -> None:
    """Build the supervisor graph, construct the orchestrator, run it."""
    supervisor_graph: SupervisorGraph = build_supervisor_graph(agent_dependencies=agent_deps)

    orchestrator = RuntimeOrchestrator(
        sensor_inventory=sensor_inventory,
        engine=engine,
        supervisor_graph=supervisor_graph,
        cell_state_manager=cell_state_manager,
        sampler=sample_local_conditions,
        tick_interval_seconds=SMOKE_TICK_INTERVAL_SEC,
        location_count=1
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
    pg = get_pg_gateway()
    try:
        engine, sensor_inventory = load_scenario_from_db("lpnf-south", pg)

        cell_state_manager = CellStateManager(
            world_grid=engine.grid,
            sensor_inventory=sensor_inventory,
        )

        agent_dependencies = build_agent_deps(engine, cell_state_manager, pg_gateway=pg)
        asyncio.run(run_orchestrator(engine, sensor_inventory, cell_state_manager, agent_dependencies))
    finally:
        pg.close()


if __name__ == "__main__":
    main()
