# 02 — Cluster Agent (Stub Mode)

## Teaching goal
Student writes their first LangGraph graph — state schema, nodes, edges, reducers — and understands the graph as a state machine before any LLM is involved.

## I/O
- In: `ClusterAgentState` with `cluster_id`, `sensor_events` (list of `SensorEvent`), and `trigger_event` (last event in the list)
- Out: `ClusterAgentState` with `anomalies` (list of `AnomalyFinding`) and `status: "complete"`
- Populated by: supervisor's `fan_out_to_clusters` (reads `events_by_cluster` from supervisor state)
- Files created: `src/agents/cluster/state.py`, `src/agents/cluster/graph.py`

## Must cover
- [ ] TypedDict state — what it is, why not Pydantic
- [ ] Reducers — `append_events` and `add_messages`; without these, node returns REPLACE not accumulate
- [ ] Three nodes: `ingest_events` (bookkeeping), `classify` (the brain), `report_findings` (output + store write)
- [ ] Conditional edge — even in stub mode, `route_after_classify` exists for the error path and for Session 3 swap
- [ ] `AnomalyFinding` — what it is; this is the contract between cluster agent and supervisor
- [ ] Store injection — `store: Optional[BaseStore] = None` in node signature, `builder.compile(store=store)`; NOT in TypedDict
- [ ] GOTCHA: `from __future__ import annotations` must NOT be in `graph.py` — breaks store injection
- [ ] Cluster agent does NOT query resources, does NOT know about other clusters
- [ ] `build_cluster_agent_graph(llm=None)` — the dual-mode builder pattern
- [ ] `pytest tests/agents/test_cluster.py -v`



## Tutorial Notes

### Assets
- LangGraph graph - for llm
- LangGraph graph - for stubs ??
- High level flow of data coming into  the cluster - from the test cases only and findings being returned to the test case
- LangGraph graph - for stubs ??

### LLM mode

- [ ] `build_cluster_agent_graph()` — builder function; accepts `llm=None`; wires different topology depending on whether LLM is provided
- [ ] `ingest_events` — first node; sets `status: "processing"`, clears errors; bookkeeping only, no classification
- [ ] `_make_classify_llm_node` — HOF (higher-order function) that wraps the LLM node in a closure; explain why: lets us inject the LLM without threading it through state; also the right pattern if we add sidecars later (e.g. Temporal.io)
- [ ] `classify_llm` — the closure returned by the factory; invokes the LLM with current messages; returns an `AIMessage` (may contain tool calls — does NOT return findings directly)
- [ ] `route_after_classify_llm` — **router function, not a node**; inspects last AI message for `tool_calls`; returns `"tool_node"`, `"parse_findings"`, or `"__end__"`
- [ ] `_parse_llm_findings` — runs after the ReAct loop exits; parses JSON from the LLM's final message and converts it to a list of `AnomalyFinding`
- [ ] `report_findings` — final node; reads `anomalies` from state, writes each finding to the LangGraph Store under `("incidents", cluster_id)`; returns `{}` (no state change needed)

### Stub mode

- [ ] `classify` — stub node; produces a hardcoded `AnomalyFinding` with `anomaly_type: "stub_placeholder"`; registered under the same node name `"classify"` as the LLM version so graph topology is identical
- [ ] `route_after_classify` — **router function, not a node**; in stub mode always returns `"report_findings"` unless `status == "error"`

