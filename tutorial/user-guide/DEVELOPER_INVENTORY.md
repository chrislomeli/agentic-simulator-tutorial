# OGAR Developer Inventory

**Project**: OGAR (domain-agnostic event-driven agent testbed)  
**Purpose**: LangGraph + Kafka + K8s agent framework with wildfire as reference domain

---

## Table of Contents
- [Configuration](#configuration)
- [World Engine (Generic Framework)](#world-engine-generic-framework)
- [Sensors](#sensors)
- [Transport Layer](#transport-layer)
- [Agents (LangGraph)](#agents-langgraph)
- [Tools (LangGraph)](#tools-langgraph)
- [Bridge](#bridge)
- [Resources](#resources)
- [Domains - Wildfire](#domains---wildfire)
- [Actuators](#actuators)
- [Workflow](#workflow)

---

## Configuration

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/config.py` | Centralized settings using pydantic-settings. Loads from .env file or environment variables. | **Classes**: `Settings` (API keys, LangSmith config, Kafka/Temporal endpoints)<br>**Functions**: `get_settings()` (cached singleton), `apply_langsmith()` (sets env vars for LangGraph) |

---

## World Engine (Generic Framework)

The domain-agnostic simulation core that can model any cellular automaton (wildfire, ocean, disease, etc.)

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/world/generic_engine.py` | Central coordinator for simulation tick loop. Advances environment, runs physics, applies state events, records ground truth. | **Classes**: `GenericWorldEngine[C]` (tick loop coordinator), `GenericGroundTruthSnapshot` (evaluation data)<br>**Methods**: `tick()` (advance 1 step), `run(ticks)` (run N steps), `inject_state()` (scenario setup), `get_snapshot()` (retrieve history) |
| `src/world/generic_grid.py` | Domain-agnostic 3D grid of cells. Handles topology (neighbors, bounds, iteration) but never interprets cell state. | **Classes**: `GenericTerrainGrid[C]` (3D cell grid)<br>**Methods**: `get_cell()`, `neighbors()`, `update_cell_state()`, `cells_where()` (query by predicate), `snapshot()`, `summary_counts()` (aggregate by label) |
| `src/world/cell_state.py` | Abstract base for domain-specific cell states. Cells are lightweight containers pairing coordinates with typed state. | **Classes**: `CellState` (ABC for domain states), `GenericCell[C]` (coordinate + state container)<br>**Abstract Methods**: `summary_label()` (for logging) |
| `src/world/environment.py` | Abstract base for domain-specific environment (ambient conditions affecting the whole grid). | **Classes**: `EnvironmentState` (ABC for weather/ambient)<br>**Abstract Methods**: `tick()` (evolve environment), `to_dict()` (serialize for ground truth) |
| `src/world/physics.py` | Abstract base for domain-specific physics modules. Defines how the world evolves. | **Classes**: `PhysicsModule[C]` (ABC for domain physics), `StateEvent[C]` (cell state change event)<br>**Abstract Methods**: `initial_cell_state()`, `tick_physics()` (compute state changes), `summarize()` (domain summary) |
| `src/world/grid.py` | Canonical enums for wildfire domain (shared across old and new code). | **Enums**: `TerrainType` (FOREST, GRASSLAND, ROCK, WATER, SCRUB, URBAN), `FireState` (UNBURNED, BURNING, BURNED) |
| `src/world/sensor_inventory.py` | First-class sensor placement management. Tracks which sensors are at which grid positions. Experimental knobs for thinning, failure injection, coverage analysis. | **Classes**: `SensorInventory`<br>**Methods**: `register()`, `register_auto()`, `get_sensor()`, `get_position()`, `all_sensors()`, `layer_types()`, `layer_positions()`, `coverage_ratio()`, `thin()`, `thin_layer()`, `inject_failure()`, `inject_bulk_failure()`, `emit_all()` |
| `src/world/weather.py` | **LEGACY** - Replaced by `domains/wildfire/environment.py`. Kept for reference. | **Classes**: `WeatherState` (old weather model) |

---

## Sensors

Abstract sensor framework + publisher loop

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/sensors/base.py` | Abstract base for all sensors. Handles SensorEvent envelope assembly, tick tracking, failure modes. Subclasses only implement `read()`. | **Classes**: `SensorBase` (ABC), `FailureMode` (NORMAL, STUCK, DROPOUT, DRIFT, SPIKE)<br>**Methods**: `emit()` (produce SensorEvent), `read()` (abstract - domain payload), `health()` (confidence score), `set_failure_mode()` |
| `src/sensors/publisher.py` | Async loop that ticks all sensors and enqueues events. Advances world engine if wired. | **Classes**: `SensorPublisher`<br>**Methods**: `run(ticks)` (main loop), `stop()` (graceful shutdown) |

---

## Transport Layer

Event queue and schemas (pre-Kafka)

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/transport/schemas.py` | The canonical SensorEvent envelope. Domain-agnostic routing + opaque payload. | **Classes**: `SensorEvent` (Pydantic model)<br>**Fields**: event_id, source_id, source_type, cluster_id, timestamp, sim_tick, confidence, payload, metadata<br>**Methods**: `create()` (factory with auto UUID/timestamp) |
| `src/transport/queue.py` | In-process async event queue (asyncio.Queue wrapper). Will be replaced by Kafka consumer. | **Classes**: `SensorEventQueue`<br>**Methods**: `put()`, `get()`, `task_done()`, `qsize()`, `empty()`, `join()` |
| `src/transport/topics.py` | Kafka topic name constants and helpers. | **Constants**: `EVENTS_ANOMALY`, `AGENTS_DECISIONS`, `COMMANDS_ACTUATORS`, `RESULTS_ACTUATORS`<br>**Functions**: `sensor_topic(cluster_id)`, `all_sensor_topic_pattern()` |

---

## Agents (LangGraph)

LangGraph subgraphs for cluster analysis and supervisor coordination

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/agents/cluster/state.py` | State schema for cluster agent LangGraph subgraph. | **Classes**: `ClusterAgentState` (TypedDict), `AnomalyFinding` (TypedDict)<br>**Fields**: cluster_id, workflow_id, sensor_events (with append_events reducer), trigger_event, messages (add_messages reducer), anomalies, status, error_message<br>**Functions**: `append_events()` (custom reducer, caps at 50 events) |
| `src/agents/cluster/graph.py` | Cluster agent LangGraph subgraph. Supports stub (deterministic) and LLM modes. Analyzes sensor events from one cluster. | **Functions**: `build_cluster_agent_graph(llm, store)` (graph builder), `ingest_events()` (node), `classify()` (stub node), `_make_classify_llm_node()` (LLM node factory), `_parse_llm_findings()` (extract JSON from LLM), `report_findings()` (write to Store), `route_after_classify()`, `route_after_classify_llm()`<br>**Constants**: `CLASSIFY_SYSTEM_PROMPT`, `cluster_agent_graph` (module-level compiled stub) |
| `src/agents/supervisor/state.py` | State schema for supervisor agent LangGraph graph. | **Classes**: `SupervisorState` (TypedDict)<br>**Fields**: active_cluster_ids, cluster_findings (aggregate_findings_reducer), messages, pending_commands, situation_summary, status, error_message<br>**Functions**: `aggregate_findings_reducer()` (dedupe by finding_id) |
| `src/agents/supervisor/graph.py` | Supervisor agent LangGraph graph. Fans out to cluster agents via Send API, correlates findings, issues actuator commands. | **Functions**: `build_supervisor_graph(llm, store)` (graph builder), `fan_out_to_clusters()` (Send API fan-out), `run_cluster_agent()` (wrapper node), `assess_situation()` (stub), `decide_actions()` (stub), `_make_assess_llm_node()`, `_parse_assessment()`, `_make_decide_llm_node()`, `_parse_commands()`, `dispatch_commands()` (write to Store), routers<br>**Constants**: `ASSESS_SYSTEM_PROMPT`, `DECIDE_SYSTEM_PROMPT` |

---

## Tools (LangGraph)

LangGraph tools for agent reasoning

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/tools/sensor_tools.py` | Tools for cluster agent LLM to query sensor data. Uses module-level state holder pattern. | **Classes**: `_SensorToolState` (mutable holder)<br>**Functions**: `set_tool_state()`, `clear_tool_state()`, `get_recent_readings()` (@tool), `get_sensor_summary()` (@tool), `check_threshold()` (@tool), `get_cluster_status()` (@tool)<br>**Constants**: `SENSOR_TOOLS` (list for binding) |
| `src/tools/supervisor_tools.py` | Tools for supervisor LLM to query aggregated findings. Uses module-level state holder pattern. Also holds optional `ResourceInventory` for resource tools. | **Classes**: `_SupervisorToolState` (mutable holder — findings + resource_inventory)<br>**Functions**: `set_supervisor_tool_state()`, `clear_supervisor_tool_state()`, `get_all_findings()` (@tool), `get_findings_by_cluster()` (@tool), `get_finding_summary()` (@tool), `check_cross_cluster()` (@tool - detects correlated anomalies)<br>**Constants**: `SUPERVISOR_TOOLS` (list for binding) |
| `src/tools/resource_tools.py` | LangGraph tools for supervisor LLM to query resource availability and preparedness. Reads from shared supervisor tool state. | **Functions**: `_get_inventory()`, `set_resource_tool_state()` (convenience), `clear_resource_tool_state()` (convenience), `get_resource_summary()` (@tool), `get_resources_by_cluster()` (@tool), `get_resources_by_type()` (@tool), `check_preparedness()` (@tool — gap detection)<br>**Constants**: `RESOURCE_TOOLS` (list for binding) |

---

## Bridge

Event routing from queue to agents

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/bridge/consumer.py` | Async consumer that reads SensorEvents from queue and dispatches to cluster agent graphs. Batches events per cluster. | **Classes**: `EventBridgeConsumer`<br>**Methods**: `run(max_events)` (main loop), `stop()`, `_invoke_agent()` (invoke cluster graph)<br>**Attributes**: collected_findings, events_consumed, invocations |

---

## Resources

Preparedness assets that exist on the world grid (queryable state, not event producers)

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/resources/base.py` | Pydantic model for preparedness assets. Resources *are* data — no ABC, no subclass required. Status transitions, capacity management, serialisation. | **Classes**: `ResourceBase` (Pydantic BaseModel), `ResourceStatus` (enum: AVAILABLE, DEPLOYED, EN_ROUTE, OUT_OF_SERVICE)<br>**Fields**: resource_id, resource_type, cluster_id, status, grid_row, grid_col, capacity, available, mobile, metadata<br>**Methods**: `deploy()`, `send_en_route()`, `release()`, `disable()`, `consume()`, `restore()`, `to_summary_dict()`<br>**Properties**: `utilization`, `is_available` |
| `src/resources/inventory.py` | Manages resource placement, status transitions, and readiness queries. Mirrors SensorInventory pattern. | **Classes**: `ResourceInventory`<br>**Methods**: `register()`, `unregister()`, `get_resource()`, `get_resources_at()`, `all_resources()`, `by_type()`, `by_cluster()`, `by_status()`, `deploy()`, `release()`, `readiness_summary()`, `coverage_by_cluster()`, `reduce_resources()`, `disable_resources()`, `reset_all()` |

---

## Domains - Wildfire

Wildfire-specific implementations of the generic framework

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/domains/wildfire/cell_state.py` | Per-cell state for wildfire simulation. Implements CellState ABC. | **Classes**: `FireCellState` (Pydantic model)<br>**Fields**: terrain_type, vegetation, fuel_moisture, slope, fire_state, fire_intensity, fire_start_tick<br>**Methods**: `summary_label()`, `is_burnable` (property), `ignited()` (immutable state transition), `extinguished()` |
| `src/domains/wildfire/environment.py` | Weather conditions for wildfire. Implements EnvironmentState ABC. Correlated random-walk drift. | **Classes**: `FireEnvironmentState` (Pydantic model)<br>**Fields**: temperature_c, humidity_pct, wind_speed_mps, wind_direction_deg, pressure_hpa, drift configs<br>**Methods**: `tick()` (evolve weather with correlations), `wind_vector()` (compass → grid direction), `to_dict()` |
| `src/domains/wildfire/physics.py` | Heuristic fire spread model. Implements PhysicsModule[FireCellState]. Stochastic cellular automaton. | **Classes**: `FirePhysicsModule`<br>**Methods**: `initial_cell_state()`, `tick_physics()` (compute spread events), `summarize()`, `_spread_probability()` (wind/slope/fuel/humidity factors), `_compute_humidity_factor()`<br>**Note**: Placeholder model - can be replaced with Rothermel or ML model |
| `src/domains/wildfire/scenarios.py` | Pre-built wildfire scenarios. Returns configured GenericWorldEngine instances and optional ResourceInventory. | **Functions**: `create_basic_wildfire()` (10×10 grid: forest north, grassland south, rock ridge with gap, urban SE, lake NW, ignition at (7,2), SW wind), `create_wildfire_resources()` (sample resources: 2 firetrucks, 1 ambulance, 1 hospital, 1 helicopter), `create_full_wildfire_scenario()` (returns engine + resources tuple) |
| `src/domains/wildfire/sensors.py` | Fire-specific sensors that sample from GenericWorldEngine[FireCellState]. Each adds Gaussian noise. | **Classes**: `TemperatureSensor` (ambient + radiant heat), `HumiditySensor` (RH%), `WindSensor` (speed + direction), `SmokeSensor` (PM2.5 from fire + wind), `BarometricSensor` (pressure), `ThermalCameraSensor` (2D heat grid)<br>**All inherit from**: `SensorBase` and implement `read()` |

---

## Actuators

Abstract actuator framework (output direction)

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/actuators/base.py` | Abstract base for all actuators. Symmetric to sensors but for output. Handles ActuatorCommand envelope. | **Classes**: `ActuatorCommand` (Pydantic model - routing + payload), `ActuatorResult` (Pydantic model - outcome), `ActuatorBase` (ABC)<br>**Methods**: `ActuatorCommand.create()` (factory), `ActuatorResult.success_result()`, `ActuatorResult.failure_result()`, `ActuatorBase.execute()` (abstract), `ActuatorBase.handle()` (public entry with routing guard) |

---

## Workflow

Abstraction layer over Temporal (currently asyncio stub)

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `src/workflow/runner.py` | Abstract interface for durable workflow execution. Swappable runtime (asyncio stub now, Temporal later). | **Classes**: `WorkflowRunner` (ABC), `WorkflowStatus` (enum: RUNNING, COMPLETED, FAILED, UNKNOWN)<br>**Abstract Methods**: `start()` (idempotent workflow start), `signal()` (deliver signal to running workflow), `get_status()` |
| `src/workflow/stub.py` | Asyncio-based implementation of WorkflowRunner. Uses Tasks + Queues instead of Temporal. | **Classes**: `AsyncioWorkflowRunner`<br>**Methods**: `start()` (create Task with dedup), `signal()` (put on queue), `get_status()`, `receive_signal()` (stub-only helper for workflow functions), `shutdown()` (cancel all tasks)<br>**Note**: No crash recovery, no persistent history - replaced by Temporal in production |

---

## Architecture Summary

### Data Flow

```
World Engine (tick loop)
    ↓
Sensors (emit readings)
    ↓
SensorEventQueue (asyncio.Queue)
    ↓
EventBridgeConsumer (batches by cluster)
    ↓
Cluster Agent Graph (LangGraph subgraph per cluster)
    ↓
AnomalyFindings (written to Store)
    ↓
Supervisor Agent Graph (correlates cross-cluster)
    ↓
ActuatorCommands (dispatched to actuators)
```

### Key Patterns

1. **Generic Framework**: `GenericWorldEngine[C]` + `PhysicsModule[C]` allows any domain
2. **Envelope Pattern**: `SensorEvent` and `ActuatorCommand` are domain-agnostic wrappers
3. **LangGraph Store**: Cross-agent memory via namespaces `("incidents", cluster_id)` and `("situations", "global")`
4. **Send API**: Supervisor fans out to cluster agents dynamically
5. **Stub → Production**: `AsyncioWorkflowRunner` → Temporal, `SensorEventQueue` → Kafka
6. **Immutable State**: `FireCellState.ignited()` returns new instance, engine applies via `StateEvent`

### Testing Strategy

- **Stub mode**: No LLM, deterministic findings, no API keys needed
- **LLM mode**: Pass `llm` to `build_cluster_agent_graph()` and `build_supervisor_graph()`
- **Store**: Use `InMemoryStore` for dev, `AsyncPostgresStore` for production
- **Reproducibility**: Set `random.seed()` before running engine

---

## Next Steps (from TODO.md)

**In Progress:**
- Sensor periodicity (`emit_every_n_ticks`)

**High Priority:**
- Second domain (ocean/disease) to validate generalization
- LangSmith tracing integration
- Notebook update for new API

**Medium Priority:**
- Kafka swap (replace `SensorEventQueue`)
- K8s deployment (Helm charts)

**Known Issues:**
- Named Cells not working (all cells are GenericCells - ABC issue?)
- Test failures in `tests/transport/test_queue.py` and `tests/workflow/test_runner.py`
- README outdated (still says "symbolic-music")

---

## File Count Summary

- **Configuration**: 1 file
- **World Engine**: 7 files (6 generic + 1 legacy)
- **Sensors**: 2 files
- **Transport**: 3 files
- **Agents**: 4 files (2 cluster + 2 supervisor)
- **Tools**: 3 files
- **Bridge**: 1 file
- **Resources**: 2 files
- **Domains (Wildfire)**: 5 files
- **Actuators**: 1 file
- **Workflow**: 2 files

**Total**: 31 core source files (excluding `__init__.py`)
