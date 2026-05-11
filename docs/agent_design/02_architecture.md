# Architecture

The work integrates with the existing pipeline. Nothing parallel.

## Existing pipeline (do not duplicate)

```
scenario_loader.load_scenario_from_package(...)
  → GenericWorldEngine + SensorInventory + ResourceInventory

RuntimeOrchestrator(sensor_inventory, engine, supervisor_graph)
  ├── SensorPublisher  ── drives engine.tick(), samples local_conditions
  │                       per sensor, emits SensorEvent
  ├── CellStateManager ── collates events into CollatedRecords by cluster
  └── SupervisorGraph
        ├── fans out to ClusterAgent per cluster
        └── aggregates cluster_score + cluster_findings
```

Key files:

- `src/main.py` — composition root.
- `src/domains/wildfire/scenario_loader.py` — loads scenario JSON.
- `src/runtime/orchestrator.py` — runtime loop and the `sampler` seam.
- `src/sensors/publisher.py` — async sensor publisher.
- `src/domains/wildfire/sampler.py` — *fire-aware* sampler (currently unused; see `03_validation.md`).
- `src/agents/supervisor/graph.py` — supervisor graph, fans out to cluster agents.

## What we're adding

Three single-responsibility components feed an **assembler** that produces the cluster agent's input.

```
   ┌──────────────────────────────┐
   │ A. Potential heatmap service │  per-cell scoring + cluster aggregation
   └────────────┬─────────────────┘
                │
   ┌────────────┴─────────────────┐
   │ B. Resource posture service  │  per-cluster snapshot from ResourceInventory
   └────────────┬─────────────────┘
                │
   ┌────────────┴─────────────────┐
   │ C. ICS-209 prior service     │  historical percentiles for similar profiles
   └────────────┬─────────────────┘
                │
                ▼
        ┌───────────────┐
        │   Assembler   │  composes the bird's-eye payload per cluster
        └──────┬────────┘
               │
               ▼
   ClusterAgent reasons over the payload
   SupervisorGraph synthesizes regional sufficiency
```

The assembler is **not** its own component. It's a thin function inside (or right next to) the orchestrator that calls A, B, C and stitches the result. No reasoning lives in the assembler.

## Bird's-eye payload (what the cluster agent receives)

```yaml
cluster: cluster_north
potential:        # from A
  cells_extreme: 3
  cells_high: 11
  hotspots: [...]
resources:        # from B
  engines: 3
  dozers: 1
  helitack: 0
  staging_distance_min: { road: 15, helo: null }
historical_prior: # from C
  similar_incidents: 7
  peak_engines: { p25: 3, p50: 5, p75: 8 }
  containment_pct_24h: { p25: 30, p50: 55, p75: 80 }
```

## Component boundaries (the rules)

- **A** knows about engine state and grid only. Knows nothing about resources or history.
- **B** knows about `ResourceInventory` only. Knows nothing about risk or history.
- **C** knows about historical records only. Knows nothing about current state.
- The **assembler** knows about A, B, C. Components do not know about the assembler.
- The **agent** does the synthesis. Components do not produce verdicts.

## Single-responsibility test

If a component would need to be opened for two unrelated reasons (e.g., risk calculation changes *and* resource inventory schema changes), it's doing too much. Split it.
