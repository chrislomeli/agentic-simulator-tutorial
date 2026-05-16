# Wildfire Agentic Advisor — Step 02: Supervisor Graph + Orchestrator Skeleton

> **Step 2 of 9** — The main LangGraph pipeline wired end-to-end for the first time. All nodes are passthrough stubs.

## This Step

Step 02 introduces the `RuntimeOrchestrator` and the `SupervisorGraph`. The world engine from step 01 is now connected to a real LangGraph pipeline — but every node in that pipeline is a stub that logs and passes state through unchanged. The value here is getting the wiring right before adding any intelligence.

### What was added

| Module | Purpose |
|--------|---------|
| `src/runtime/orchestrator.py` | `RuntimeOrchestrator` — consumes `SensorEventQueue`, drives `CellStateManager`, invokes supervisor on threshold crossings |
| `src/agents/supervisor/graph.py` | `build_supervisor_graph()` — compiles the supervisor `StateGraph` |
| `src/agents/supervisor/state.py` | `SupervisorState`, `RiskScore`, custom reducers (`max_cluster_score`, `merge_cluster_findings`) |
| `src/agents/supervisor/nodes.py` | Stub implementations: `fan_out_to_clusters`, `assess_situation`, `dispatch_commands` |
| `src/agents/commons/` | Shared schemas: `TracedState`, `CellReadings`, `Metric`, `GridPosition`, `CollatedRecordRisk` |
| `main.py` | Entry point — wires engine + orchestrator + supervisor, starts the async event loop |

### What you can run

```bash
uv run python verify_setup.py
uv run python main.py              # full pipeline — stub outputs only
uv run python -m pytest tests/ -v
```

The pipeline runs end-to-end. The supervisor is invoked whenever `CellStateManager` detects a threshold crossing. `fan_out_to_clusters` returns an empty `Send` list (no cluster agents yet), `assess_situation` logs the empty findings, and `dispatch_commands` logs and exits.

### Key design points

- **`CellStateManager`** is the threshold gate between raw sensor events and the graph. It maintains per-cell running state and only triggers the supervisor when readings cross configured thresholds — preventing the graph from being invoked on every tick.
- **`SupervisorState` reducers** — `max_cluster_score` and `merge_cluster_findings` are defined now even though cluster agents don't exist yet. They must be in place before the Send API fan-out is added in step 03 because LangGraph resolves the state schema at compile time.
- **`TracedState`** — the base class for all agent states. Carries `session_id`, `status`, and `error`. The `@node_executor` decorator (step 05) requires this contract; establishing it now means step 05 is a drop-in.

---

## Full System Overview

```mermaid
flowchart TD
    subgraph World["World Engine (step_01)"]
        WE["GenericWorldEngine\nRothermel fire physics · tick loop"]
        SI["SensorInventory"]
        SP["SensorPublisher"]
        WE --> SP
        SI --> SP
    end

    SP -->|SensorEvent| Q["AsyncIO Queue"]

    subgraph ORC["Orchestrator (step_02) ← YOU ARE HERE"]
        CM["CellStateManager\nper-cell state · threshold detection"]
        Q --> CM
    end

    CM -->|"triggered clusters"| SV

    subgraph MAIN["Supervisor Graph (step_02) ← YOU ARE HERE"]
        SV["fan_out_to_clusters\nSTUB — returns empty list"]
        AS["assess_situation\nSTUB — logs + passes through"]
        DC["dispatch_commands\nSTUB — logs + exits"]
        SV --> AS --> DC
    end

    CLUSTER["Cluster Agents\nadded in step_03"] -.->|not yet| SV
    LOGISTICS["Logistics Agent\nadded in step_04"] -.->|not yet| AS
    ADV["Advisory Store"] -.->|not yet| DC
```

### Data Model

```mermaid
erDiagram
    TERRAIN {
        int     grid_row          PK
        int     grid_column       PK
        string  terrain
        float   fuel_moisture
        float   slope
        float   temperature_c
        float   humidity_pct
        float   wind_speed_mps
        geo     location          "PostGIS geography(Point,4326)"
    }
    SENSORS {
        string  sensor_id         PK
        int     grid_row          FK
        int     grid_column       FK
        string  sensor_type
        string  cluster_id
        float   noise_std
        geo     location          "PostGIS geography(Point,4326)"
    }
    RESOURCES {
        int     resource_id       PK
        string  resource_type
        string  nwcg_type
        int     capacity_water_gal
        int     personnel
        geo     location          "PostGIS geography(Point,4326)"
    }
    ADVISORIES {
        uuid     id               PK
        datetime created_at
        string   status
        int      epicenter_row
        int      epicenter_column
        int      urgency_level
        string   recommendation
    }
    TERRAIN ||--o{ SENSORS : "sensor placed at grid cell"
```

## Step Progression

| Step | What it adds |
|------|--------------|
| 01 | World engine, sensor inventory, publisher, transport queue, store backends |
| **02** | **Supervisor graph + orchestrator skeleton — pipeline wired, all nodes stub** |
| 03 | Cluster (risk) agent skeleton + Send API fan-out |
| 04 | Logistics agent skeleton |
| 05 | `@node_executor` decorator — metrics + exception handling |
| 06 | Jinja2 prompt registry |
| 07 | LLM registry + cluster agent live |
| 08 | Logistics tools + logistics agent live |
| 09 | Advisory dispatch completed — full pipeline operational |
