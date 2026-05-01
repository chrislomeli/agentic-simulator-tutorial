# Session 6: Routing Helpers

---

## What you're doing and why

Every conditional edge in every graph in this system makes the same three-way decision:

1. Did the previous node fail? → route to `END` (bail out)
2. Did the previous node finish its work? → route to the completion target (often `END`, sometimes another node)
3. Otherwise → continue to the next node

The cluster agent's `route_after_classify` function from session 2 is exactly this pattern, written by hand. The supervisor will need it. The evaluator will need it. Every graph you add later will write the same 6 lines, slightly differently each time, and they'll drift.

This session extracts the pattern into one helper — `goto(node)` — that you'll use everywhere.

---

## Why this matters

It's a small abstraction with an outsized payoff:

- **Consistency** — every graph routes errors the same way. There's one place to change error-routing behaviour, not seven.
- **Readability** — `builder.add_conditional_edges("classify", goto("report_findings"))` reads better than a 10-line custom router that does the same thing.
- **Forward compatibility** — when you add a feature like "retry once on error before exiting", you change `_route_base` in one place and every graph picks it up.

Routers that need extra logic (e.g., the LLM-mode `route_after_classify_llm` in session 7, which checks for `tool_calls` on the last message) still write custom code. But they can compose `_route_base` for the error/complete branches.

---

## What you're building

| File | What it contains |
|------|-----------------|
| `src/agents/routing.py` | `_route_base()` core function + `goto()` factory |

---

## Coding guidance

### `_route_base(state, *, next_node, on_completion=END) -> str`

The shared core. Takes:
- `state` — the agent state (Pydantic `BaseModel`, attribute access)
- `next_node` (kwarg-only) — where to go if status is non-terminal
- `on_completion` (kwarg-only, default `END`) — where to go if status is `COMPLETED`

Returns the name of the next node (or `END`).

Body:
- If `state.status == StatusValue.ERROR` → log a warning with the agent identifier and error_message, return `END`.
- If `state.status == StatusValue.COMPLETED` → return `on_completion`.
- Otherwise → return `next_node`.

**Compare against the StrEnum members, not raw strings.** `StatusValue.COMPLETED.value` is `"completed"` (past tense, with the `d`). The journal_agent original used `"complete"` which would silently never match — easy mistake to repeat.

### `goto(node, on_completion=END) -> Callable`

A closure factory. Returns a router function suitable for `add_conditional_edges`. The returned function takes `state` and calls `_route_base(state, next_node=node, on_completion=on_completion)`.

That's the whole file. ~30 lines including imports and module docstring.

### Pydantic vs. dict access

This project uses Pydantic state models everywhere. Use attribute access (`state.status`), not dict access (`state.get("status")`). If you ever need to support both (because some test passes a raw dict), use a helper:

```
def _get(state, attr): return state.get(attr) if isinstance(state, dict) else getattr(state, attr, None)
```

But avoid that complexity if your tests construct proper state objects.

### Logging the error path

When you route to `END` because of an error, log enough context that you can correlate with the `node_trace` records from session 5:
- The agent identifier (`cluster_id` or `workflow_id` or `session_id`, whichever the state has)
- The `error_message`

`logger.warning("Routing to END (id=%s, error=%s)", ..., ...)` is fine — keep it lightweight; the heavy structured logging happens in `node_trace`.

---

## How session 2's code changes

The `route_after_classify` function in `src/agents/cluster/cluster_graph.py` is a candidate to be replaced by `goto("report_findings")`. The current version:

```
def route_after_classify(state) -> Literal["report_findings", "__end__"]:
    if state.status == StatusValue.ERROR:
        return "__end__"
    return "report_findings"
```

After this session, it becomes one line in the graph builder:

```
builder.add_conditional_edges("classify", goto("report_findings"))
```

**You don't have to replace it now.** The session 2 version still works. But session 7's LLM mode is a good moment to do the swap — you'll be touching that file anyway.

---

## What `goto()` does NOT replace

The LLM-mode router in session 7 (`route_after_classify_llm`) needs to inspect `state.messages[-1]` for `tool_calls`. That's ReAct-specific logic — keep it as a custom function. But its error/complete branches can still delegate to `_route_base`:

```
def route_after_classify_llm(state) -> str:
    if state.status == StatusValue.ERROR:
        return END
    last = state.messages[-1] if state.messages else None
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tool_node"
    return "parse_findings"
```

The `goto()` helper is for the simple three-way case. Custom routers handle the rest.

---

## Don't forget

- Import `END` from `langgraph.graph` (not from `langgraph.constants`). The two are the same string but the public surface is `langgraph.graph.END`.
- `goto` returns a `Callable`, not a string. The mistake to avoid is calling it as `add_conditional_edges("classify", goto("report_findings")(state))` — the closure-vs-call confusion.
- The kwargs on `_route_base` are keyword-only (use `*,` in the signature). It prevents future bugs where someone passes `on_completion` positionally.

---

## Tests worth writing

- `goto("next_node")` returns a callable.
- The callable applied to a state with `status=PROCESSING` returns `"next_node"`.
- With `status=COMPLETED` it returns the `on_completion` value (default `END`).
- With `status=ERROR` it returns `END` regardless of `on_completion`.
- With `on_completion="audit"` and `status=COMPLETED` it returns `"audit"`.

---

*Next: Session 7 puts all four pieces together. The cluster agent's stub `classify` becomes an LLM-powered ReAct loop — using the registry from session 3, the prompt from session 4, the tracer from session 5, and the routing helpers from session 6.*
