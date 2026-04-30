# Resource System Implementation Plan

**Status**: ✅ COMPLETE  
**Last Updated**: 2026-04-05  

This file tracks the implementation of the Resource system. Update the status of each step as you complete it. Any session (Cascade, Claude Code, etc.) should read this file first and continue from the last completed step.

---

## Design Reference

See memory or the design section in DEVELOPER_INVENTORY.md for full rationale. Key points:

- **ResourceBase** is a Pydantic BaseModel (not an ABC). Resources *are* data.
- **ResourceStatus** enum: AVAILABLE, DEPLOYED, EN_ROUTE, OUT_OF_SERVICE
- **ResourceInventory** mirrors SensorInventory pattern (registration, queries, status transitions, capacity, readiness queries, scenario knobs). No emit, no tick.
- **Domain subclasses optional** — wildfire resources are just ResourceBase instances with field values.
- **Agent integration** via `resource_tools.py` following the module-level state holder pattern.
- **Ground truth** — add optional `resource_summary` to `GenericGroundTruthSnapshot`.

---

## Implementation Steps

### Step 1: `src/resources/__init__.py`
**Status**: ✅ COMPLETE  
Create package init. Re-export `ResourceBase`, `ResourceStatus`, `ResourceInventory`.

### Step 2: `src/resources/base.py`  
**Status**: ✅ COMPLETE  
Create `ResourceBase` (Pydantic BaseModel), `ResourceStatus` (str Enum), and optionally a `GridPosition` helper.

Fields for ResourceBase:
- `resource_id: str` — stable identifier, e.g. "firetruck-7"
- `resource_type: str` — opaque tag, e.g. "firetruck", "hospital"
- `cluster_id: str` — routing key (same concept as sensors)
- `status: ResourceStatus` — current operational state
- `grid_row: int` — row position on world grid
- `grid_col: int` — column position on world grid
- `capacity: float` — max capability (50 beds, 500 gallons)
- `available: float` — current remaining capability
- `mobile: bool = False` — can this resource change location?
- `metadata: Dict[str, Any] = {}` — domain-specific extras

Key methods on ResourceBase:
- `deploy(row, col)` — set status to DEPLOYED, update location if mobile
- `release()` — set status back to AVAILABLE
- `consume(amount)` — reduce available by amount
- `restore(amount)` — increase available (capped at capacity)
- `utilization` property — `1.0 - (available / capacity)` if capacity > 0
- `to_summary_dict()` — for ground truth snapshots and tool responses

Follow existing patterns:
- Match docstring style from `sensors/base.py` and `actuators/base.py`
- Match field documentation style from `transport/schemas.py`

### Step 3: `src/resources/inventory.py`
**Status**: ✅ COMPLETE  
Create `ResourceInventory` mirroring `SensorInventory` structure.

Must have:
- `__init__(grid_rows, grid_cols)` — same as SensorInventory
- `register(resource)` — add resource, index by type and cluster
- `unregister(resource_id)` — remove resource
- `get_resource(resource_id)` — lookup by ID
- `get_resources_at(row, col)` — all resources at a position
- `all_resources()` — list all
- `by_type(resource_type)` — filter by type
- `by_cluster(cluster_id)` — filter by cluster
- `by_status(status)` — filter by status
- `deploy(resource_id, row, col)` — transition to DEPLOYED
- `release(resource_id)` — transition to AVAILABLE
- `readiness_summary()` — dict of counts/capacity by type and status (for tools and ground truth)
- `coverage_by_cluster()` — which clusters have what resources
- `size` property

Scenario knobs:
- `reduce_resources(resource_type, keep_fraction)` — like SensorInventory.thin()
- `disable_resources(resource_type, fraction)` — set fraction to OUT_OF_SERVICE

### Step 4: `src/tools/resource_tools.py`
**Status**: ✅ COMPLETE  
**Note**: Resource tools read from the shared `_SupervisorToolState` rather than a separate state holder. `set_resource_tool_state()`/`clear_resource_tool_state()` are convenience wrappers for standalone testing.
LangGraph tools for supervisor to query resources. Follow exact pattern of `supervisor_tools.py`.

Module-level state holder:
- `_ResourceToolState` class with `inventory: Optional[ResourceInventory]`
- `set_resource_tool_state(inventory)` / `clear_resource_tool_state()`

Tools (all decorated with `@tool`):
- `get_resource_summary()` — overall readiness: counts, capacity, availability by type
- `get_resources_by_cluster(cluster_id)` — what's available near a cluster
- `get_resources_by_type(resource_type)` — all resources of a type with status
- `check_preparedness(cluster_id)` — is this cluster adequately covered?

Export `RESOURCE_TOOLS` list for binding.

### Step 5: Wire tools into supervisor graph
**Status**: ✅ COMPLETE  
**Note**: `build_supervisor_graph()` accepts optional `resource_inventory` parameter. When provided in LLM mode, `RESOURCE_TOOLS` are added to the combined tool list. Stub mode is unaffected.
Update `src/agents/supervisor/graph.py` and `src/tools/supervisor_tools.py`:
- Add resource tools to `SUPERVISOR_TOOLS` list (or create a combined list)
- Update `set_supervisor_tool_state()` to accept optional `ResourceInventory`
- Update `_make_assess_llm_node()` and `_make_decide_llm_node()` to pass inventory

**BE CAREFUL**: This touches existing working code. Make minimal changes. Don't break stub mode.

### Step 6: Update `GenericGroundTruthSnapshot`
**Status**: ✅ COMPLETE  
**Note**: Added `resource_summary: Dict[str, Any] = field(default_factory=dict)` to the dataclass. The engine stays domain-agnostic — scenario scripts populate the field after `tick()` if desired.
Add `resource_summary: Dict[str, Any] = field(default_factory=dict)` to the dataclass.
Update `GenericWorldEngine.tick()` to populate it if a `ResourceInventory` is available.

**BE CAREFUL**: The engine is currently domain-agnostic and doesn't know about resources. The cleanest approach is to make the engine optionally accept a ResourceInventory and include its summary if present. Alternatively, keep it outside the engine and let the scenario script snapshot resources separately.

### Step 7: Update wildfire scenario
**Status**: ✅ COMPLETE  
**Note**: Added `create_wildfire_resources()` and `create_full_wildfire_scenario()`. Existing `create_basic_wildfire()` is unchanged (backward compatible).
Update `src/domains/wildfire/scenarios.py` `create_basic_wildfire()` to:
- Create a `ResourceInventory`
- Register sample resources (2 firetrucks, 1 ambulance, 1 hospital, 1 helicopter)
- Return the inventory alongside the engine (or attach it to the engine)

### Step 8: Update `DEVELOPER_INVENTORY.md`
**Status**: ✅ COMPLETE  
Add the new files to the inventory document.

### Step 9: Tests
**Status**: ✅ COMPLETE (78 tests, all passing)  
Write tests for:
- `ResourceBase` — creation, deploy/release, consume/restore, utilization
- `ResourceInventory` — register, query, status transitions, readiness summary, scenario knobs
- `resource_tools` — tool functions return correct data

---

## Notes for Continuation

- All steps complete. 517 total tests pass (78 new resource tests + 439 existing).
- No regressions in existing tests.
- The `pyproject.toml` `[tool.hatch.build.targets.wheel]` packages list should include `"src/resources"` if building a wheel.
- Follow existing code style exactly (docstrings, logging, type hints).
- The user's bar is "senior developer would approve" — no shortcuts, no "fix later" stubs.
