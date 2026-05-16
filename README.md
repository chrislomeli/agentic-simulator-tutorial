# Wildfire Agentic Advisor — Tutorial

A step-by-step tutorial for building a production-grade multi-agent AI application using [LangGraph](https://github.com/langchain-ai/langgraph). Each numbered directory is a self-contained, runnable checkpoint. Start at `step_01` and work forward, or jump directly to any step to see the system at that stage of development.

---

## What We Are Building

The application is a wildfire early-warning and resource advisory system. A physics-based world simulator continuously generates sensor telemetry across a geo-gridded terrain. An agentic pipeline consumes that telemetry, assesses fire risk using parallel LLM agents, evaluates nearby suppression resources, and issues a structured advisory when conditions warrant a response.

The wildfire domain is the vehicle — the engineering patterns are the point. After completing all nine steps you will have implemented from scratch:

- A **supervisor / worker** multi-agent hierarchy with a LangGraph `StateGraph` at each level
- **Parallel subgraph fan-out** using LangGraph's Send API with custom state reducers as the synchronisation barrier
- A **ReAct tool-calling loop** with domain-specific tools and structured output extraction
- A **node decorator** providing cross-cutting metrics, exception capture, and distributed tracing for every graph node
- A **versioned Jinja2 prompt registry** fully decoupled from agent code
- A **role-based LLM registry** for routing different roles to different providers and models
- A **dual-backend data store** (PostgreSQL with PostGIS + in-memory mock) behind a shared interface

---

## System Architecture

### Runtime Data Flow

```mermaid
flowchart TD
    subgraph World["World Engine (step_01)"]
        WE["GenericWorldEngine\nRothermel fire physics · tick loop"]
        SI["SensorInventory\ntemperature · humidity\nwind speed · wind direction"]
        SP["SensorPublisher\nnoisy readings with failure modes"]
        WE -->|"engine.tick()"| SP
        SI -->|provides sensors| SP
    end

    SP -->|SensorEvent| Q["AsyncIO Queue\nSensorEventQueue"]

    subgraph ORC["Orchestrator (step_02)"]
        CM["CellStateManager\nper-cell state · threshold detection"]
        Q --> CM
    end

    CM -->|"triggered clusters\ncluster_id + CellReadings"| SV

    subgraph MAIN["Supervisor Graph (step_02)"]
        SV["fan_out_to_clusters\nreturns list[Send]"]
        AS["assess_situation"]
        DC["dispatch_commands"]
        SV --> AS --> DC
    end

    subgraph CLUSTER["Cluster (Risk) Agents — run in parallel (step_03)"]
        CA1["Cluster Agent A\nupdate_world → evaluate → report_risk"]
        CA2["Cluster Agent B"]
        CAN["Cluster Agent N"]
    end

    SV -->|"Send(cluster_id, readings)"| CA1 & CA2 & CAN
    CA1 & CA2 & CAN -->|"risk scores + CollatedRecordRisk\nmerged by custom reducers"| AS

    AS --> LA

    subgraph LOGISTICS["Logistics Agent — ReAct loop (step_04)"]
        LA["logistics_agent\nLLM with tools bound"]
        TN["ToolNode\nsector_heatmap · nearby_resources\nfire_behavior_query"]
        EP["extract_plan\nstructured output → LogisticsAssessment"]
        LA <-->|tool calls| TN
        LA --> EP
    end

    EP -->|"ResourceAdvisory\nif urgency warrants"| ADV["Advisory Store\nPostgreSQL · mock"]
```

### Data Model

The world state and agent outputs are persisted through a store layer with both a PostgreSQL (PostGIS) implementation and an in-memory mock for testing.

```mermaid
erDiagram
    TERRAIN {
        int     grid_row          PK
        int     grid_column       PK
        string  cell_key
        string  terrain
        float   vegetation
        float   fuel_moisture
        float   slope
        int     cell_size_ft
        float   temperature_c
        float   humidity_pct
        float   wind_speed_mps
        float   wind_direction_deg
        geo     location          "PostGIS geography(Point,4326)"
        string  region
    }
    SENSORS {
        string  sensor_id         PK
        int     grid_row          FK
        int     grid_column       FK
        string  sensor_type
        string  cluster_id
        float   noise_std
        float   lat
        float   long
        geo     location          "PostGIS geography(Point,4326)"
    }
    RESOURCES {
        int     resource_id       PK
        string  agency
        string  unit_id
        string  resource_category
        string  resource_type
        string  nwcg_type
        int     capacity_water_gal
        int     pump_gpm
        int     personnel
        string  station_name
        string  station_address
        float   lat
        float   long
        geo     location          "PostGIS geography(Point,4326)"
    }
    WILDFIRE_ACTIVITY {
        date    imsr_date
        string  fire_name
        string  unit
        int     fire_size_acres
        int     percent_containment
        int     personnel
        int     crews
        int     engines
        int     helicopters
        string  gacc
        int     fire_priority
    }
    ADVISORIES {
        uuid     id               PK
        datetime created_at
        string   status           "SENT · SUPPRESSED · ACKNOWLEDGED"
        int      epicenter_row
        int      epicenter_column
        string   location_description
        string   situation
        int      urgency_level    "1=Cocked Pistol … 4=Fade Out"
        string   notes
        string   recommendation
    }
    TERRAIN ||--o{ SENSORS : "sensor placed at grid cell"
```

---

## Step Progression

Each directory is a standalone runnable project. The table shows exactly what each step adds over the previous one.

| branch   | Directory | What it adds                                                                                                                                                                                    |
|----------|-----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| step_01  | `agentic-simulator-step_01` | **World engine** — Rothermel fire physics, terrain grid, wildfire domain cell states, sensor inventory, `SensorPublisher`, `SensorEventQueue`, PostgreSQL + mock store backends                 |
| step_02  | `agentic-simulator-step_02` | **Supervisor graph + orchestrator skeleton** — `RuntimeOrchestrator` wires publisher → queue → `CellStateManager` → supervisor; all graph nodes are passthrough stubs                           |
| step_03  | `agentic-simulator-step_03` | **Cluster (risk) agent skeleton** — `ClusterAgentState`, `update_world → evaluate → report_risk` subgraph; supervisor fans out via Send API; `evaluate` returns deterministic stub scores       |
| step_04  | `agentic-simulator-step_04` | **Logistics agent skeleton** — `LogisticsAgentState`, `logistics_agent → tools → extract_plan` subgraph wired into the supervisor after `assess_situation`                                      |
| step_05  | `agentic-simulator-step_05` | **`@node_executor` decorator** — wraps all node functions with per-node timing, structured exception capture, and `session_id` tracing; `TracedState` base class added                          |
| step_06  | `agentic-simulator-step_06` | **Jinja2 prompt registry** — `PromptRegistry` loads versioned templates from `prompts/templates/<name>/<version>/prompt.j2`; all agent nodes switch to rendered prompts                         |
| step_07  | `agentic-simulator-step_07` | **LLM registry + cluster agent live** — `LLMRegistry` routes roles to providers (STUB / OpenAI / Anthropic / Ollama); cluster agent `evaluate` node makes real structured-output LLM calls      |
| step_08  | `agentic-simulator-step_08` | **Logistics tools + logistics agent live** — `sector_heatmap`, `nearby_resources`, `fire_behavior_query` tools implemented; logistics ReAct loop makes real LLM calls; prompt templates added   |
| step_09  | `agentic-simulator-step_09` | **Advisory dispatch completed** — `dispatch_advisory` writes `ResourceAdvisory` to the advisory store; logistics prompts refined; full end-to-end pipeline operational                          |

---

## Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) for environment management
- An API key for your chosen LLM provider (steps 07–09 only; steps 01–06 run without one)
- PostgreSQL with PostGIS (optional — every step includes an in-memory mock backend)

```bash
cd agentic-simulator-step_01   # or whichever step you want
uv sync
uv run python verify_setup.py
```

Steps 07 and later also include `verify_llm_registry.py` and `verify_api_key.py` to confirm your LLM configuration before running the full pipeline.
