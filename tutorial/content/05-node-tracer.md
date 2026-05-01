# Session 5: Node Tracer (Per-Node Timing & Structured Logging)

---

## What you're doing and why

Every node in every graph in this system is going to need:
- Elapsed time per call
- The status the node returned (`processing`, `completed`, `error`)
- A session/run identifier so logs from concurrent agent invocations can be untangled
- Exception context if the node raises

You could sprinkle `logger.info()` calls inside every node body. That's repetitive, easy to forget, and produces inconsistent log records. Instead, this session builds a single decorator — `@node_trace` — that wraps any LangGraph node and emits a structured log record with all of the above.

A working starting point already exists at `tutorial/stash/node_tracer.py` (your own port from another project). It needs to be moved into `src/`, generalized to handle multiple state types, and wired into `configure_environment()`.

---

## Why this matters

You're going to want this sooner than you think:
- **Session 8** — full sensor-to-agent pipeline. When something goes wrong, the only honest answer to "where did it stall?" is the log of node entry/exit times.
- **Session 13** — resilience scenarios. Knowing which node burns the most wall-clock time matters for back-pressure tuning.
- **Session 14** — evaluation. Per-node timing feeds directly into the eval report.

Adding tracing to a 12-node graph after the fact is tedious. Adding the decorator now means every node you write from session 7 onward is observable for free.

---

## What you're building

| File | What it contains |
|------|-----------------|
| `src/observability/__init__.py` | Package marker |
| `src/observability/node_trace.py` | The `@node_trace(node_name=None)` decorator |
| `src/config.py` (modify) | Extend `configure_environment()` to set up the tracer's log handler |

---

## Coding guidance

### Start from `tutorial/stash/node_tracer.py`

You already have a port. The bones are right; the issues to fix:
- It imports `from src.agents.cluster.state import StatusValue, ClusterAgentState` — too narrow. The decorator should work for any state model, not just the cluster agent's.
- It only checks `'session_id' in state.model_fields`. The cluster state has `cluster_id` and `workflow_id`. Pick a primary identifier strategy (see below).

### Decorator signature

```
def node_trace(node_name: str | None = None):
    def decorator(func): ...
    return decorator
```

`node_name` lets the caller override the logged name (occasionally useful when two factory-built nodes share an inner function name). Default to `func.__name__`.

### Sync vs. async

Detect with `asyncio.iscoroutinefunction(func)` and return either a sync or async wrapper. The journal_agent original handles this correctly — keep that pattern.

Both wrappers do the same shape:
1. `start = perf_counter()`
2. Pull a session identifier from state (see below)
3. Call `func(state)` — sync or `await` for async
4. Log on success with `_log_result(name, elapsed, session_id, result)`
5. On exception: log with `logger.exception(...)` and re-raise

**Do not swallow exceptions.** The graph's error handling is the user's job — your job is to record what happened.

### Pulling a session identifier

The state types vary. Make the lookup forgiving:

- If `state.model_fields` contains `session_id` and `state.session_id` is set, use it.
- Else, look for `cluster_id`, `workflow_id`, `run_id` (in that order) — pick the first that's present and non-empty.
- Fallback: `f"<{state.__class__.__name__}>"`

This way the cluster agent logs use `cluster_id`, the supervisor logs use `workflow_id`, and tests using a random state class still produce something useful.

### Structured logging

Always pass details through `extra={...}`, never via the message string. The shape:

```
logger.info(
    "node completed",
    extra={
        "node": name,
        "session_id": session_id,
        "elapsed_ms": round(elapsed * 1000),
        "status": str(status),
    },
)
```

`extra` keys flow into the `LogRecord`. A custom formatter can then pull `%(node)s`, `%(elapsed_ms)s`, etc. without parsing the message.

For errors (when `result["status"] == StatusValue.ERROR`), use `logger.warning` and add `error_message` to `extra`. For raised exceptions, `logger.exception` (which captures the traceback automatically) — no `extra={"traceback": ...}` needed.

### Wire up the formatter in `configure_environment()`

The tracer's logger needs its own handler with a format string that surfaces the `extra` fields. Otherwise the root logger's basic format silently drops them.

In `configure_environment()`:
- Get the tracer logger by name: `logging.getLogger("src.observability.node_trace")`
- Set `logger.propagate = False` so the root handler doesn't double-log a basic-format copy
- Add a `StreamHandler` (and optionally a `FileHandler`) with a format string like:
  `"%(asctime)s  %(name)-35s  [%(node)s] %(elapsed_ms)sms  %(status)s  %(message)s"`

Pattern stolen from journal_agent's `config_builder.py` — that's the right template.

---

## Don't forget

- The decorator must use `@functools.wraps(func)` so the wrapped node keeps its name and docstring (LangGraph uses these in some places).
- Type hint the return as `Callable[..., Union[dict, Coroutine[Any, Any, dict]]]` — node functions return either a partial state dict or a coroutine yielding one.
- Don't import `ClusterAgentState` at module top level — that creates a circular dependency. The decorator should be state-type-agnostic.
- If you're writing tests for the decorator: capture log records with `caplog.records` and assert on `record.node`, `record.elapsed_ms`, etc. — the structured fields, not the message string.

---

## Tests worth writing

- `@node_trace`-decorated sync function: returns its result unchanged; emits one INFO record with `node`, `elapsed_ms`, `status` in `extra`.
- `@node_trace`-decorated async function: same shape via `await`.
- Decorated function that raises: re-raises the exception; emits one log record at the exception level with the node name.
- Decorated function returning `{"status": StatusValue.ERROR, ...}`: log level is WARNING, `error_message` is present in `extra`.

---

## Usage from session 7 onward

```
from src.observability.node_trace import node_trace

@node_trace("classify")
def classify(state: ClusterAgentState) -> dict:
    ...
```

That's the whole interface. Every node from session 7 forward should have it.

---

*Next: Session 6 introduces a small `goto()` helper that standardizes how every graph routes errors and completion — the last piece of plumbing before you wire the LLM into the cluster agent in session 7.*
