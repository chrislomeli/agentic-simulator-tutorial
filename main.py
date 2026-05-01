"""
main.py — entry point for the world simulator tutorial.

Session 02 stage:
  1. Tick the world engine a few times and print fire-behavior snapshots
     so you can see the ground truth your agent will eventually try to infer.
  2. Build the cluster agent (stub mode), invoke it with a hand-crafted
     SensorEvent, and print the AnomalyFinding it produces.

Run from the project root:
  python main.py

This script depends on the editable install adding `src/` to the Python path.
If you see ImportError, run: uv pip install -e ".[llm]" --group dev
"""
import logging

# configure_logging() must come before all project imports so that
# module-level loggers (e.g. the compiled cluster_agent_graph) are
# captured by structlog from the first record onward.
from logging_config import configure_logging
configure_logging(level=logging.INFO)

from agents.cluster.graph import build_cluster_agent_graph
from agents.cluster.state import ClusterAgentState
from transport.schemas import SensorEvent

PRINT_GRAPH = True


def demo_cluster_agent() -> None:
    print("=== Cluster agent demo ===")

    event = SensorEvent.create(
        source_id="temp-n1",
        source_type="temperature",
        cluster_id="cluster-north",
        payload={"celsius": 52.4},
    )

    graph = build_cluster_agent_graph()

    if PRINT_GRAPH:
        with open("graph.png", "wb") as f:
            f.write(graph.get_graph().draw_mermaid_png())

    initial_state = ClusterAgentState(
        cluster_id="cluster-north",
        workflow_id="demo-run-1",
        trigger_event=event,
        error_message=None,
    )
    result = graph.invoke(initial_state)

    print(f"Status:   {result['status']}")
    print(f"Findings: {len(result['anomalies'])}")
    for finding in result["anomalies"]:
        print(f"  - {finding.anomaly_type} (confidence={finding.confidence})")
        print(f"    {finding.summary}")
    print()


def main() -> None:
    demo_cluster_agent()


if __name__ == "__main__":
    main()
