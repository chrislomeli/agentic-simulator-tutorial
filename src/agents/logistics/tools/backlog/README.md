# Logistics Agent Tools

This package contains the tools the logistics LLM can call on demand
during a risk-response evaluation.

---

## What "tool" means here

A **tool** is a function whose schema is published to the remote LLM
(via `llm.bind_tools([...])`) so that Claude can ask the local process
to invoke it during a conversation. Mechanically:

1. Claude emits a `tool_use` block: `{name: "X", input: {...}}`
2. The local agent loop runs the function with that input
3. The function returns a JSON-serializable result
4. The result is fed back to Claude as a `tool_result` block
5. Claude continues reasoning with the new information

Claude itself never opens a socket, reads a file, or hits a database.
The local process is the executor; tools are the menu of capabilities
the local process publishes to the LLM.

---

## The contract for tools in this project

> **Tools are internal query APIs over simulator state.**
> They are not external integrations.

This project is a *simulation* — the simulator is the source of truth.
Tools that call out to real-world services (RAWS, LANDFIRE, live weather)
would either duplicate or contradict simulated data, which is a category
error. Every tool in this package answers a question about
**state the simulator already owns**.

The production parallel is clean: in a real deployment, the same tool
interface would be backed by real systems (a timeseries DB, a dispatch
service, an actual physics engine). Only the *implementation* changes;
the tool's input schema, output schema, and docstring stay the same.
Claude doesn't know — and shouldn't know — whether it's talking to a
simulator or a production system. That's the point.

---

## What lives here

| Tool                   | What it answers                                                                      | Backing state                                                          |
|------------------------|--------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| `get_resources_within` | "What crews/engines are reachable within N minutes of this cell?"                    | `ResourceInventory` (`src/resources/inventory.py`)                     |
| `simulate_spread_from` | "If this cell ignited now, where would the fire go in N ticks?"                      | `RothermelFirePhysicsModule` + a copy of the world grid                |
| `get_wind_history`     | "What have wind speed and direction looked like at this cell over the last N ticks?" | `_CellSnapshot` ring buffer (**TODO — does not exist yet, see below**) |
| `get hotspots`         | "What have wind speed and direction looked like at this cell over the last N ticks?" | `_CellSnapshot` ring buffer (**TODO — does not exist yet, see below**) |
| `set hotspots`         | "What have wind speed and direction looked like at this cell over the last N ticks?" | `_CellSnapshot` ring buffer (**TODO — does not exist yet, see below**) |
#

### What is *not* a tool

Some questions look tool-shaped but should be left to the LLM's judgment.
The clearest example: **"What resources do we need?"** is not a tool —
that's the LLM's actual reasoning job. Building a
`compute_resource_needs(...)` tool would push the judgment back into
deterministic code, which is exactly what the LLM is supposed to do.
Let the LLM look at `simulate_spread_from()`, `get_resources_within()`,
and the cell context, then produce its plan.

---

## File layout

```
src/agents/logistics/tools/
├── README.md           ← you are here
├── __init__.py         ← public exports
├── resources.py        ← get_resources_within
├── spread.py           ← simulate_spread_from
└── wind_history.py     ← get_wind_history
```

Each tool module exports:

- **An input Pydantic model** — what Claude must pass as arguments.
- **An output Pydantic model** — what the tool returns.
- **A `make_<tool_name>` factory** — closes over runtime dependencies
  (inventory, physics module, etc.) and returns a `StructuredTool`.

This factory pattern matches `make_evaluate_node()` in
`src/agents/cluster/nodes.py`. Tools can't be module-level functions
because they need access to live runtime objects. Closing over deps in
a factory keeps the wiring explicit and testable.

---

## How tools wire into the agent

The high-level shape (to be built in `graph.py` later):

```python
def build_logistics_agent_graph(*, agent_deps: AgentDependencies) -> CompiledGraph:
    tools = [
        make_get_resources_within(inventory=agent_deps.resource_inventory),
        make_simulate_spread_from(
            world_grid=agent_deps.world_grid,
            physics=agent_deps.physics,
        ),
        make_get_wind_history(cell_state_manager=agent_deps.cell_state_manager),
    ]

    llm = agent_deps.llm_registry.get("logistics").bind_tools(tools)
    tool_node = ToolNode(tools)  # langgraph.prebuilt

    builder = StateGraph(LogisticsAgentState)
    builder.add_node("plan", make_plan_node(llm=llm, prompt_registry=...))
    builder.add_node("tools", tool_node)
    builder.add_conditional_edges("plan", route_after_plan)  # → "tools" or END
    builder.add_edge("tools", "plan")  # loop back after tool result
    builder.add_edge(START, "plan")
    return builder.compile()
```

The agent loop is: **plan → (maybe call tools) → back to plan → repeat
until the LLM produces a final answer with no `tool_use`.** That loop
is the entire reason tools work — Claude is stateless across turns, so
the local code holds the conversation state and routes between LLM
calls and tool calls.

---

## How Claude decides to call a tool

Claude only sees three things about each tool:

1. The **tool name** (the function name, or the `name=` kwarg on `@tool`).
2. The **input schema** (the Pydantic `args_schema`).
3. The **docstring** on the inner function.

That's the entire contract. If the docstring is vague, Claude calls the
tool at the wrong times. If the schema is loose, Claude passes garbage.
**The docstring is not an implementation note for humans — it is the
prompt fragment Claude reads to decide when to call the tool and how
to interpret what it returns.** Write it accordingly:

- State *when* the tool should be used, not just what it does.
- Mention any constraints ("only AVAILABLE resources", "max 50 results").
- Describe the output shape Claude can expect.
- Avoid implementation details Claude doesn't need ("uses Haversine distance" is noise; "returns straight-line travel time in minutes" is signal).

---

## How to add a new tool

1. Create a new file in this directory: `<tool_name>.py`.
2. Define `<ToolName>Input(BaseModel)` — the args schema Claude will see.
3. Define `<ToolName>Output(BaseModel)` — the return shape.
4. Write `make_<tool_name>(*, dep1, dep2) -> StructuredTool` — the
   factory that closes over runtime deps and returns the decorated tool.
5. Inside the inner function, write the docstring **for Claude**, not
   for humans. (See "How Claude decides to call a tool" above.)
6. Re-export from `__init__.py`.
7. Wire into `build_logistics_agent_graph` in `graph.py`.

Pattern across all tools is the same — pick the closest existing tool
file and copy its skeleton.

---

## Open infrastructure TODOs

Tools depend on backing state. Some of that state doesn't exist yet:

### Ring buffer in `_CellSnapshot` for `get_wind_history`

`CellStateManager` currently keeps only the *latest* metric per type
per cell. To answer historical-trend questions, `_CellSnapshot` needs
a small ring buffer per metric type — say, the last N readings as
`(timestamp, value)` tuples. Suggested shape:

```python
# in src/world/cell_state_manager.py
@dataclass
class _CellSnapshot:
    ...
    # Ring buffer of recent readings per metric type.
    # Bounded length (e.g. 100) — older entries dropped on overflow.
    metric_history: dict[str, deque[tuple[datetime, float]]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=100))
    )

    def update_metric(self, metric: Metric, cluster_id: str) -> None:
        self.metrics[metric.type] = metric
        self.seen_types.add(metric.type)
        self.cluster_id = cluster_id
        self.metric_history[metric.type].append((metric.timestamp, metric.value))  # NEW
```

Until that lands, `get_wind_history` will raise `NotImplementedError`.

### Physics-side hypothetical run for `simulate_spread_from`

`RothermelFirePhysicsModule.tick_physics()` mutates the live grid. The
spread tool needs a *hypothetical* — copy the grid, ignite the source
cell, run N ticks on the copy, return the result without touching the
real simulation. Two options:

- Add a `simulate_from(grid_snapshot, source_cell, ticks)` classmethod
  to `RothermelFirePhysicsModule` that operates on a copy.
- Or do the copy at the tool layer: `copy.deepcopy(world_grid)` then
  call existing `tick_physics` on the copy.

The classmethod is cleaner (encapsulates the copy semantics); the
deepcopy is faster to wire in. Recommend the classmethod once it's
needed by more than one caller.

### `LogisticsAgentDependencies`

`AgentDependencies` (in `src/agents/commons/agent_dependencies.py`)
currently exposes `llm_registry`, `prompt_registry`, `store`. Logistics
tools need three more handles: `resource_inventory`, `world_grid` /
`physics`, and `cell_state_manager`. Either extend the existing class
with those as `Optional` fields, or make a new `LogisticsAgentDependencies`
that adds them. The factory pattern in this package keeps the tools
agnostic to that choice — they take their deps as explicit kwargs.

---

## Why the prompt format matters more than the function body

The most common failure mode of LLM-callable tools is not buggy
implementation — it is **a tool that works perfectly but never gets
called, or gets called for the wrong situation**. Spend time on the
docstring and the schema. A great function with a vague docstring is
worse than a mediocre function with a precise one.
