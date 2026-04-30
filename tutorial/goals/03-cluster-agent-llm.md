# 03 — Cluster Agent (LLM Mode)

## Teaching goal
Student adds an LLM + ReAct loop to the existing graph by swapping one node — demonstrating that graph structure and reasoning engine are separable.

## I/O
- In: same `ClusterAgentState` as Session 2
- Out: same `AnomalyFinding` output, but now produced by LLM reasoning over tool results
- Files created: `src/tools/sensor_tools.py`
- Files modified: `src/agents/cluster/graph.py`

## Must cover
- [ ] `@tool` decorator — docstring IS the LLM's API description; type hints matter
- [ ] The four sensor tools: `get_recent_readings`, `get_sensor_summary`, `check_threshold`, `get_cluster_status`
- [ ] Module-level state holder pattern — tools can't take state as a parameter, so state is loaded before each LLM invocation
- [ ] `llm.bind_tools(SENSOR_TOOLS)` — how tools get attached to the LLM
- [ ] `ToolNode(SENSOR_TOOLS)` — auto-dispatches tool calls from AI messages
- [ ] ReAct cycle: `classify_llm → route_after_classify_llm → tool_node → classify_llm` (the cycle)
- [ ] `route_after_classify_llm` — checks `tool_calls` on last AI message to decide loop vs. exit
- [ ] `_parse_llm_findings` — fourth node added in LLM mode; extracts JSON from LLM's final message and converts to `AnomalyFinding`; runs after the loop exits
- [ ] Factory function `_make_classify_llm_node(llm_with_tools)` — captures LLM in closure; this is the injectable pattern
- [ ] Only one node swapped (stub `classify` → `classify_llm`), plus `tool_node` and `parse_findings` added — `ingest_events`, `report_findings`, state schema unchanged
- [ ] `pytest tests/agents/test_cluster.py tests/tools/ -v`
