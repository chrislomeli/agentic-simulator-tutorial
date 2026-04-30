# 05 — Supervisor Agent (Stub Mode)

## Teaching goal
Student builds the supervisor graph and understands how it fans out to multiple cluster agents using the Send API, then collects results.

## I/O
- In: `SupervisorState` with `active_cluster_ids` and `cluster_findings`
- Out: `SupervisorState` with `situation_summary` and `pending_commands`
- Files created: `src/agents/supervisor/state.py`, `src/agents/supervisor/graph.py`

## Must cover
- [ ] Send API — `Send("node_name", state)` fans out N parallel invocations inside the supervisor (e.g. process findings from multiple clusters in parallel); NOT how cluster agents are called (that's the EventBridgeConsumer)
- [ ] Why a separate state schema — supervisor state and cluster agent state are different shapes
- [ ] `aggregate_findings_reducer` — merges findings from parallel Send invocations
- [ ] Supervisor vs. cluster relationship: supervisor owns orchestration, cluster owns per-cluster analysis
- [ ] Stub supervisor just counts findings — same stub-first pattern as Session 2
- [ ] `build_supervisor_graph(llm=None)` — same dual-mode builder pattern
- [ ] `graph.invoke({...})` — supervisor runs synchronously (not async) after pipeline completes
- [ ] `pytest tests/agents/test_supervisor.py -v`
