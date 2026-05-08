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

from agents.commons.geo import cell_size_miles
from agents.supervisor.graph import build_supervisor_graph
from agents.supervisor.state import SupervisorGraph, SupervisorState
from logging_config import configure_logging
import datetime

from agents.commons.schemas import GridPosition, Metric, CollatedRecord, TerrainContext, CoverageSummary, TimeWindow

# configure_logging() must come before all project imports so that
# module-level loggers are captured by structlog from the first record.
configure_logging(level=logging.INFO)


from agents.commons.schemas import CollatedRecord, RiskAssessment  # noqa: E402
from config import LLMLabel, build_llm_registry, get_settings, models  # noqa: E402
from domains.wildfire.scenario_loader import load_scenario_from_package  # noqa: E402
from domains.wildfire.world_builder.regions import get_region  # noqa: E402

# Smoke-test cadence — fast enough that the demo finishes in a few
# seconds, slow enough that publisher and consumer can interleave.
SMOKE_TICKS = 3
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



def cluster_data():
    """
    Scenario
    Two cells in two differt regions (clusters) have triggered.
    As sensor readings come in from our sensors scattered across the park, they update the CollatedRecord that collects the last reading as a metric

    At the "cluster-cuyama" station
        Cell (1,4) has received readings for temperature, humidity, wind_speed, and wind_direction and stored them as "metrics"
        This is enough data to require evaluation by our agent

    At the "cluster-sb-coast" station
        Cell (20,2) has also received complete readings for temperature, humidity, wind_speed, and wind_direction
        and is also sent

    """
    return {
        'cluster-cuyama': [
            CollatedRecord(cluster_id='cluster-cuyama', triggered=True, position=GridPosition(row=1, col=4),
                           window=TimeWindow(
                               start=datetime.datetime(2026, 5, 7, 23, 7, 14, 488541, tzinfo=datetime.timezone.utc),
                               end=datetime.datetime(2026, 5, 7, 23, 7, 14, 488680, tzinfo=datetime.timezone.utc),
                               sim_tick_start=0,
                               sim_tick_end=0), metrics=[
                    Metric(type='temperature', value=24.9, signal_strength=0.2928932188134524,
                           source_id='RAWS-CARRIZO-temp',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488541, tzinfo=datetime.timezone.utc)),
                    Metric(type='humidity', value=26.1, signal_strength=0.2928932188134524,
                           source_id='RAWS-CARRIZO-humidity',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488644, tzinfo=datetime.timezone.utc)),
                    Metric(type='wind_speed', value=8.1, signal_strength=0.2928932188134524,
                           source_id='RAWS-CARRIZO-wind',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488680, tzinfo=datetime.timezone.utc)),
                    Metric(type='wind_direction', value=49.9, signal_strength=0.2928932188134524,
                           source_id='RAWS-CARRIZO-wind',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488680, tzinfo=datetime.timezone.utc))],
                           coverage=CoverageSummary(present=['temperature', 'humidity', 'wind_direction', 'wind_speed'],
                                                    absent=[], strongest_signal=0.2928932188134524,
                                                    weakest_signal=0.2928932188134524),
                           terrain=TerrainContext(terrain_type='GRASSLAND', vegetation=0.3, fuel_moisture=0.08,
                                                  slope=0.0)),
        ],
    'cluster-sb-coast': [
            CollatedRecord(cluster_id='cluster-cuyama', triggered=True, position=GridPosition(row=20, col=2),
                           window=TimeWindow(
                               start=datetime.datetime(2026, 5, 7, 23, 7, 14, 488541, tzinfo=datetime.timezone.utc),
                               end=datetime.datetime(2026, 5, 7, 23, 7, 14, 488680, tzinfo=datetime.timezone.utc),
                               sim_tick_start=0,
                               sim_tick_end=0), metrics=[
                    Metric(type='temperature', value=24.9, signal_strength=0.2928932188134524,
                           source_id='RAWS-SB-temp',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488541, tzinfo=datetime.timezone.utc)),
                    Metric(type='humidity', value=26.1, signal_strength=0.2928932188134524,
                           source_id='RAWS-SB-humidity',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488644, tzinfo=datetime.timezone.utc)),
                    Metric(type='wind_speed', value=8.1, signal_strength=0.2928932188134524,
                           source_id='RAWS-SB-wind',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488680, tzinfo=datetime.timezone.utc)),
                    Metric(type='wind_direction', value=49.9, signal_strength=0.2928932188134524,
                           source_id='RAWS-SB-wind',
                           position=GridPosition(row=2, col=5),
                           timestamp=datetime.datetime(2026, 5, 7, 23, 7, 14, 488680, tzinfo=datetime.timezone.utc))],
                           coverage=CoverageSummary(present=['temperature', 'humidity', 'wind_direction', 'wind_speed'],
                                                    absent=[], strongest_signal=0.2928932188134524,
                                                    weakest_signal=0.2928932188134524),
                           terrain=TerrainContext(terrain_type='GRASSLAND', vegetation=0.3, fuel_moisture=0.08,
                                                  slope=0.0)),
        ]
    }


def main() -> None:
    print("GET WORLD")
    region = get_region("lpnf-south")
    engine, sensor_inventory, _ = load_scenario_from_package("lpnf-south")

    print_world_summary(engine, sensor_inventory, region)

    print("\n\nINVOKE GRAPH")
    supervisor_graph: SupervisorGraph = build_supervisor_graph()
    initial_state = SupervisorState(clusters=cluster_data())
    supervisor_graph.invoke(initial_state)


if __name__ == "__main__":
    main()
