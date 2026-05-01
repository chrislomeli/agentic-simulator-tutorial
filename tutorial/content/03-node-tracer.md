# Session 3: Node Tracer & Structured Logging

---
```bash
Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
        modified:   main.py
        modified:   pyproject.toml
        deleted:    src/agents/cluster/cluster_graph.py
        new file:   src/agents/cluster/graph.py
        new file:   src/agents/cluster/node_tracer.py
        new file:   src/agents/cluster/nodes.py
        modified:   src/agents/cluster/state.py
        modified:   src/bridge/pipeline_runner.py
        new file:   src/logging_config.py
        modified:   uv.lock
```


---

## What you're doing and why

You want per-node observability: elapsed time, status, and error context — captured automatically without sprinkling `logger.info()` calls inside every node body.

This session:
1. Moves the `node_trace` decorator (your port from another project) into `src/agents/cluster/node_tracer.py`
2. Installs `structlog` for production-grade structured logging (not "good enough" plain JSON)
3. Replaces the default Python logging with structlog's stdlib bridge so every log record — including those from LangGraph and LangChain — flows through a single JSON pipeline
4. Adds `session_id` to `ClusterAgentState` so all logs from a single graph invocation can be correlated

By the end, every `@node_trace`-decorated node emits a structured JSON record with `node`, `session_id`, `elapsed_ms`, and `status` fields, automatically queryable in log aggregators.

---

## Why this matters

Logging is infrastructure, not an afterthought. The `@node_trace` decorator scales with your graph: once built, every node you add from session 7 onward is observable for free.

Structured logging (JSON, not plain text) matters because:
- Plain text logs require `grep` and regex hacks to extract timing or errors
- JSON logs are queryable: `jq 'select(.node == "classify" and .status == "error")'`
- Production log aggregators (Datadog, Splunk, Grafana Loki) expect structured records

---

## What you're building

| File | What it contains |
|------|-----------------|
| `src/agents/cluster/node_tracer.py` | The `@node_trace(node_name=None)` decorator |
| `src/logging_config.py` | `configure_logging()` using structlog's stdlib bridge |
| `src/agents/cluster/state.py` (modify) | Add `session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))` |
| `src/agents/cluster/nodes.py` (modify) | Wrap nodes with `@node_trace()` |
| `src/agents/cluster/graph.py` | Refactored: builder only, imports nodes from `nodes.py` |
| `main.py` (modify) | Call `configure_logging()` before any project imports |
| `pyproject.toml` (modify) | Add `structlog>=25.5.0` dependency |

---

## Coding guidance

### `src/agents/cluster/node_tracer.py`

Start from your existing port. Changes needed:

**Module docstring** — explain what the decorator does and why it's structured logging, not plain text.

**Imports** — use `structlog` instead of stdlib `logging`:
```python
import structlog
logger = structlog.get_logger(__name__)
```

**State type flexibility** — the decorator can't hardcode `ClusterAgentState`. Extract the session ID forgivingly:

```python
if 'session_id' in state.model_fields:
    session_id = state.session_id or f"<{state.__class__.__name__}>"
else:
    session_id = f"<{state.__class__.__name__}>"
```

**Structlog calling convention** — pass structured fields as keyword arguments, not `extra={}`:

```python
logger.info(
    "node completed",
    node=name,
    session_id=session_id,
    elapsed_ms=elapsed_ms,
    status=str(status),
)
```

**Sync and async** — use `asyncio.iscoroutinefunction(func)` to detect and wrap both. Both do the same shape: time the call, pull session_id, log result or exception.

### `src/logging_config.py`

One function: `configure_logging(level: int = logging.INFO) -> None`.

The function:
1. Builds a processor chain (timestamp, logger name, exception renderer)
2. Configures structlog to use the stdlib bridge (`structlog.stdlib.LoggerFactory()`)
3. Creates a handler with `ProcessorFormatter` that turns stdlib LogRecords into JSON
4. Clears and replaces the root logger's handlers

Why structlog's bridge? Because `logging.getLogger(__name__)` calls in LangGraph, LangChain, and your own code all produce stdlib LogRecords. The bridge lets structlog intercept those records before the stdlib handler formats them, so everything emits the same JSON regardless of who called the logger.

### `main.py`

Move the import and call to the very top:

```python
from logging_config import configure_logging
configure_logging()

# Then import the rest
from agents.cluster.cluster_graph import build_cluster_agent_graph
...
```

This ensures logging is configured before any module-level code fires (like `cluster_agent_graph = build_cluster_agent_graph()` at the end of `graph.py`).

### `state.py`

Add one field:

```python
session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
```

This gives every graph invocation a unique identifier so the node tracer can tag all logs from one run together.

### `nodes.py` (formerly `cluster_graph.py`)

Decorate the node functions:

```python
from agents.cluster.node_tracer import node_trace

@node_trace("ingest_events")
def ingest_events(state: ClusterAgentState) -> dict:
    ...
```

### `graph.py` (new, formerly part of `cluster_graph.py`)

Pure builder file:

```python
from agents.cluster.nodes import (
    ingest_events, classify, make_report_findings, route_after_classify
)

def build_cluster_agent_graph(store: Optional[BaseStore] = None):
    builder = StateGraph(ClusterAgentState)
    builder.add_node("ingest_events", ingest_events)
    builder.add_node("classify", classify)
    builder.add_node("report_findings", make_report_findings(store=store))
    
    builder.add_edge(START, "ingest_events")
    ...
    compiled = builder.compile()
    return compiled
```

The graph file doesn't import logging, doesn't define nodes, doesn't know about observability. It's just wiring.

---

## Don't forget

- `configure_logging()` must be the first import in `main.py` — before any project code runs.
- `@functools.wraps(func)` so the decorator preserves the node function's `__name__` (LangGraph sometimes uses it).
- Don't use `extra={}` with structlog — pass fields as keyword arguments.
- `session_id` is pulled from state dynamically; if the state class changes, the tracer adapts automatically.

---

## Tests worth writing

After this session, the cluster agent test should pass without changes — the `@node_trace` decorator is transparent to the graph's behavior. Verify:

- `python main.py` runs and produces JSON log lines with `node`, `session_id`, `elapsed_ms`, `status` fields visible in output
- All three nodes (`ingest_events`, `classify`, `report_findings`) appear in the logs with the same `session_id`

---

*Next: Session 4 extracts prompts into a versioned registry so prompt tuning doesn't require editing graph files.*
