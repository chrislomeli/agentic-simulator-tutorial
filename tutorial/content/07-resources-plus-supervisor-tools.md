# Session 7: Resources and Preparedness Tools

---

## What you're doing and why

Sessions 5–6 gave the supervisor tools to examine *what happened* — findings from cluster agents. But findings alone don't tell you what to do. If cluster-north reports a temperature spike, the supervisor needs to know: are there firetrucks nearby? Are they available?

This session adds resource tools — a second set of `@tool` functions that query the `ResourceInventory`. Combined with the supervisor tools from Session 6, the LLM now has complete context: what happened + are we prepared → what should we do.

The key pattern is **additive tool composition**: the tool set expands based on what context you provide to `build_supervisor_graph()`. Pass a `ResourceInventory` and you get 8 tools. Don't pass one and you get 4. The graph works either way.

---

## Setup

This session builds on Sessions 5–6. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/world/ src/domains/ src/sensors/ src/transport/ src/bridge/ src/resources/ src/config.py tests/
git checkout tutorial/main -- src/agents/ src/tools/
pytest tests/agents/test_supervisor.py tests/resources/ -q   # should pass before you start
```

---

## Rubric coverage

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| Tool definition — @tool decorator | foundational | `resource_tools.py` — 4 tools querying `ResourceInventory` |
| ToolNode + bind_tools | foundational | `SUPERVISOR_TOOLS + RESOURCE_TOOLS` composed into one `ToolNode` |

---

## What you're building

| File | Change | What it contains |
|------|--------|-----------------|
| `src/tools/resource_tools.py` | **Create** | 4 `@tool` functions: `get_resource_summary`, `get_resources_by_cluster`, `get_resources_by_type`, `check_preparedness` |
| `src/agents/supervisor/graph.py` | **Modify** | Additive tool composition in `build_supervisor_graph()` — add `RESOURCE_TOOLS` when `resource_inventory` is provided |

When you're done:

```bash
pytest tests/resources/ tests/tools/ -v
```

---

## Why preparedness matters

Sessions 09–10 gave the supervisor tools to examine findings:
- `get_all_findings()` — see what cluster agents reported
- `check_cross_cluster()` — detect correlations

But findings alone don't tell you what to do. If cluster-north reports a temperature spike, the supervisor needs to know:
- **Are there firetrucks nearby?** (`get_resources_by_cluster("cluster-north")`)
- **Are they available or deployed?** (`check_preparedness("cluster-north")`)
- **Is capacity sufficient?** (`get_resource_summary()`)

This is the preparedness layer. Resources are queryable world state. The supervisor queries them to assess readiness, then decides on actions based on both findings and preparedness.

---

## The four resource tools

Resource tools give the LLM structured access to the `ResourceInventory`:

### 1. `get_resource_summary` — overall readiness

```python
@tool
def get_resource_summary() -> Dict[str, Any]:
    """Get an overall readiness summary of all resources.
    
    Returns:
        Dict with:
          - total_resources: total count
          - by_type: dict mapping resource_type to counts and capacity info
          - by_cluster: dict mapping cluster_id to resource counts
          - by_status: dict mapping status to count
    """
    inventory = _get_inventory()
    if inventory is None:
        return {"error": "No resource inventory available", "total_resources": 0}
    return inventory.readiness_summary()
```

The LLM calls this to get a high-level overview: "How many resources total? What types? How many available?"

Example output:

```python
{
    "total_resources": 8,
    "by_type": {
        "crew": {"total": 2, "available": 2, "deployed": 0, "out_of_service": 0,
                 "total_capacity": 23.0, "available_capacity": 23.0},
        "engine": {"total": 2, "available": 2, "deployed": 0, "out_of_service": 0,
                   "total_capacity": 1000.0, "available_capacity": 1000.0},
        "dozer": {"total": 1, "available": 1, "deployed": 0, "out_of_service": 0,
                  "total_capacity": 60.0, "available_capacity": 60.0},
        "hospital": {"total": 1, "available": 1, "deployed": 0, "out_of_service": 0,
                     "total_capacity": 50.0, "available_capacity": 42.0},
        "ambulance": {"total": 1, "available": 1, "deployed": 0, "out_of_service": 0,
                      "total_capacity": 2.0, "available_capacity": 2.0},
        "helicopter": {"total": 1, "available": 1, "deployed": 0, "out_of_service": 0,
                       "total_capacity": 700.0, "available_capacity": 700.0},
    },
    "by_cluster": {
        "cluster-south": {"total": 7, "available": 7, "types": ["ambulance", "crew", "dozer", "engine", "hospital"]},
        "cluster-north": {"total": 1, "available": 1, "types": ["helicopter"]},
    },
    "by_status": {"AVAILABLE": 8},
}
```

### 2. `get_resources_by_cluster` — what's nearby

```python
@tool
def get_resources_by_cluster(cluster_id: str) -> List[Dict[str, Any]]:
    """Get all resources assigned to a specific cluster.
    
    Args:
        cluster_id: The cluster to query (e.g. "cluster-north").
    
    Returns:
        List of resource summary dicts with resource_id, type, status,
        capacity, available, and location for each resource.
    """
    inventory = _get_inventory()
    if inventory is None:
        return []
    resources = inventory.by_cluster(cluster_id)
    return [r.to_summary_dict() for r in resources]
```

The LLM calls this to zoom in on one cluster: "What resources does cluster-south have?"

Example output:

```python
[
    {"resource_id": "crew-south-1", "resource_type": "crew", "cluster_id": "cluster-south",
     "status": "AVAILABLE", "grid_row": 7, "grid_col": 2, "capacity": 15.0,
     "available": 15.0, "utilization": 0.0, "mobile": False},
    {"resource_id": "engine-south-1", "resource_type": "engine", "cluster_id": "cluster-south",
     "status": "AVAILABLE", "grid_row": 7, "grid_col": 1, "capacity": 500.0,
     "available": 500.0, "utilization": 0.0, "mobile": True},
    # ... more resources
]
```

### 3. `get_resources_by_type` — all of one type

```python
@tool
def get_resources_by_type(resource_type: str) -> List[Dict[str, Any]]:
    """Get all resources of a specific type across all clusters.
    
    Args:
        resource_type: The type to query (e.g. "firetruck", "hospital").
    
    Returns:
        List of resource summary dicts for all resources of that type.
    """
    inventory = _get_inventory()
    if inventory is None:
        return []
    resources = inventory.by_type(resource_type)
    return [r.to_summary_dict() for r in resources]
```

The LLM calls this to see all resources of a type: "Where are all the engines?"

### 4. `check_preparedness` — gap analysis

```python
@tool
def check_preparedness(cluster_id: Optional[str] = None) -> Dict[str, Any]:
    """Check whether a cluster (or the whole system) is adequately resourced.
    
    Examines resource availability and capacity to provide a preparedness
    assessment. If cluster_id is provided, checks that cluster only.
    If None, checks all clusters.
    
    Returns:
        Dict with:
          - cluster_id: which cluster (or "all")
          - total_resources: count of resources in scope
          - available_resources: count with status AVAILABLE
          - resource_types_present: list of types available
          - total_capacity: sum of all capacity
          - available_capacity: sum of remaining capacity
          - utilization_pct: percentage of capacity in use
          - gaps: list of potential issues (e.g. "no medical resources")
    """
```

This is the key preparedness tool. It identifies gaps:
- "No resources currently available (all deployed or out of service)"
- "Low capacity: only 100/500 remaining (80% utilized)"
- "3/5 resources out of service"

**Fire-behavior-aware gaps:**

When `fire_behavior_summary` is provided, `check_preparedness` cross-references fireline intensity against NWCG thresholds:

```python
from tools.supervisor_tools import _state as supervisor_state
from domains.wildfire.nwcg_resources import INTENSITY_THRESHOLDS
fire_behavior = supervisor_state.fire_behavior_summary
if fire_behavior:
    intensity = fire_behavior.get("max_fireline_intensity", 0.0)
    if intensity > INTENSITY_THRESHOLDS["hand_crew"] and "crew" not in types_present:
        gaps.append(
            f"Fireline intensity {intensity:.0f} BTU/ft/s exceeds hand-crew "
            "threshold but no crews assigned to this scope"
        )
    if intensity > INTENSITY_THRESHOLDS["dozer"] and "helicopter" not in types_present:
        gaps.append(
            f"Fireline intensity {intensity:.0f} BTU/ft/s — aerial resources "
            "needed but none assigned to this scope"
        )
```

This makes gap analysis context-aware. If the fire is intense, the tool flags missing heavy resources even if light resources are present.

---

## Tool composition: building the full tool set

The supervisor graph builder combines tool sets based on what's provided:

```python
def build_supervisor_graph(
    llm: Optional[BaseChatModel] = None,
    store: Optional[BaseStore] = None,
    resource_inventory: Optional[ResourceInventory] = None,
    fire_behavior_summary: Optional[Dict] = None,
):
    if llm is not None:
        # Start with supervisor tools (4)
        all_tools = SUPERVISOR_TOOLS
        
        # Add resource tools if inventory provided (4 more)
        if resource_inventory is not None:
            all_tools = all_tools + RESOURCE_TOOLS
        
        # Add fire behavior tools if summary provided (3 more)
        if fire_behavior_summary is not None:
            all_tools = all_tools + FIRE_BEHAVIOR_TOOLS
        
        llm_with_tools = llm.bind_tools(all_tools)
        
        # Both assess and decide phases use the same ToolNode
        builder.add_node("assess_tool_node", ToolNode(all_tools))
        builder.add_node("decide_tool_node", ToolNode(all_tools))
```

This is **additive tool composition**:
- Baseline: 4 supervisor tools (findings only)
- +ResourceInventory: 8 tools (findings + preparedness)
- +fire_behavior_summary: 11 tools (findings + preparedness + fire context)

Each tool set is independently optional. Backward compatible.

---

## Shared state holder pattern

All tools read from the same `_SupervisorToolState`:

```python
# In supervisor_tools.py
class _SupervisorToolState:
    findings: List[AnomalyFinding] = []
    active_cluster_ids: List[str] = []
    resource_inventory: Optional[ResourceInventory] = None
    fire_behavior_summary: Optional[Dict[str, Any]] = None

_state = _SupervisorToolState()
```

The supervisor graph loads state before each LLM loop:

```python
# In assess_situation_llm and decide_actions_llm nodes
set_supervisor_tool_state(
    findings, cluster_ids, resource_inventory, fire_behavior_summary
)
```

Resource tools read from `_state.resource_inventory`:

```python
# In resource_tools.py
def _get_inventory() -> Optional[ResourceInventory]:
    from tools.supervisor_tools import _state as supervisor_state
    return supervisor_state.resource_inventory

@tool
def get_resource_summary() -> Dict[str, Any]:
    inventory = _get_inventory()
    if inventory is None:
        return {"error": "No resource inventory available", "total_resources": 0}
    return inventory.readiness_summary()
```

This avoids maintaining separate state holders for each tool set. All tools share one state, loaded once per supervisor execution.

---

## Running it

Here's a complete script that invokes the supervisor with resource awareness:

```python
from langchain_openai import ChatOpenAI
from agents.supervisor.graph import build_supervisor_graph
from domains.wildfire import create_full_wildfire_scenario

# Create scenario with resources
engine, resources = create_full_wildfire_scenario()

# Build supervisor with resource tools
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
graph = build_supervisor_graph(
    llm=llm,
    resource_inventory=resources,  # Adds 4 resource tools
)

# Invoke with 2 active clusters
result = graph.invoke({
    "active_cluster_ids": ["cluster-north", "cluster-south"],
    "cluster_findings": [],
    "messages": [],
    "pending_commands": [],
    "situation_summary": None,
    "status": "idle",
    "error_message": None,
})

# Inspect the result
print(f"Status: {result['status']}")
print(f"\nSituation Summary:")
print(result['situation_summary'])
print(f"\nCommands: {len(result['pending_commands'])}")

# Check what the LLM learned about resources
print(f"\nResource readiness (ground truth):")
for rtype, info in resources.readiness_summary()["by_type"].items():
    print(f"  {rtype}: {info['available']}/{info['total']} available, "
          f"{info['available_capacity']:.0f}/{info['total_capacity']:.0f} capacity")
```

**Expected output:**

```
Status: complete

Situation Summary:
Two stub findings detected from cluster-north and cluster-south. Both are placeholder findings with low confidence (0.5). Resource assessment: cluster-south has 7 resources available (2 crews, 2 engines, 1 dozer, 1 ambulance, 1 hospital). Cluster-north has 1 helicopter available. All resources are AVAILABLE with full capacity. System is well-prepared for fire response. No action needed.

Commands: 0

Resource readiness (ground truth):
  crew: 2/2 available, 23/23 capacity
  engine: 2/2 available, 1000/1000 capacity
  dozer: 1/1 available, 60/60 capacity
  ambulance: 1/1 available, 2/2 capacity
  hospital: 1/1 available, 42/50 capacity
  helicopter: 1/1 available, 700/700 capacity
```

The LLM:
1. Called `get_resource_summary()` to see overall readiness
2. Called `get_resources_by_cluster("cluster-south")` to check south coverage
3. Called `get_resources_by_cluster("cluster-north")` to check north coverage
4. Concluded all resources are available and the system is well-prepared
5. Decided no commands are needed (stub findings + adequate preparedness = no action)

**With degraded resources:**

```python
# Disable 50% of engines
resources.disable_resources("engine", fraction=0.5)

result = graph.invoke({...})
print(result['situation_summary'])
```

Output:

```
Situation Summary:
Two stub findings detected. Resource assessment shows degradation: cluster-south has 1/2 engines out of service, reducing water capacity from 1000 to 500 gallons. Recommend monitoring engine availability and considering redeployment if fire activity increases.

Commands: 1
1. [alert] → cluster-south (priority=3)
   Payload: {'message': 'Engine capacity reduced, monitor closely', 'recipients': ['ops-team']}
```

The LLM detected the gap and recommended action.

---

## What you learned: Resource tool patterns

This session introduced resource tool integration:

**1. Additive tool composition** — `SUPERVISOR_TOOLS + RESOURCE_TOOLS` = 8 tools bound to one LLM. Each tool set is independently optional.

**2. Shared state holder** — all tools read from `_SupervisorToolState`. One state load per supervisor execution.

**3. Fire-behavior-aware gaps** — `check_preparedness()` cross-references fireline intensity against NWCG thresholds when fire behavior data is available.

**4. Preparedness assessment** — the supervisor can now answer "Are we prepared?" by querying resource availability, capacity, and coverage.

**5. Same ToolNode for all** — `ToolNode(all_tools)` handles supervisor, resource, and fire behavior tools in both assess and decide phases.

**6. Backward compatibility** — pass `resource_inventory=None` to exclude resource tools. The graph works with or without them.

The supervisor now has complete context: findings (what happened) + resources (are we prepared) → decisions (what to do).

---

## Checkpoint

```bash
pytest tests/resources/ tests/tools/ -v
```

Key tests to look for:
- `test_resource_tools` — all 4 tools return correct data shapes
- `test_check_preparedness_with_gaps` — gap detection works when resources are disabled
- `test_supervisor_graph_with_resource_tools` — 8-tool supervisor graph compiles and runs

---

## Key files

- `src/tools/resource_tools.py` — 4 resource tools: `get_resource_summary`, `get_resources_by_cluster`, `get_resources_by_type`, `check_preparedness`
- `src/agents/supervisor/graph.py` — `build_supervisor_graph()` with additive tool composition
- `src/tools/supervisor_tools.py` — `_SupervisorToolState` (shared by all tool sets)
- `src/domains/wildfire/nwcg_resources.py` — NWCG intensity thresholds used by fire-aware gap checks

---

*Next: Session 8 wires everything together into a complete end-to-end pipeline: world engine → sensors → queue → cluster agents → supervisor → commands. All systems active, all tools available, full observability with LangSmith tracing.*
