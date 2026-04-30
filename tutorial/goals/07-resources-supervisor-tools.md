# 07 — Resources and Preparedness Tools

## Teaching goal
Student adds resource tools to the supervisor and understands additive tool composition — tools are optional and the graph works with or without them.

## I/O
- In: `SupervisorState` + `ResourceInventory` passed to `build_supervisor_graph(resource_inventory=...)`
- Out: `situation_summary` now includes resource assessment; `pending_commands` may include gap-driven alerts
- Files created: `src/tools/resource_tools.py`
- Files modified: `src/agents/supervisor/graph.py`

## Must cover
- [ ] The four resource tools: `get_resource_summary`, `get_resources_by_cluster`, `get_resources_by_type`, `check_preparedness`
- [ ] Additive composition: `SUPERVISOR_TOOLS + RESOURCE_TOOLS` — each set is independently optional
- [ ] Same `_SupervisorToolState` holder — `resource_inventory` field added; tools read it via `_get_inventory()`
- [ ] `check_preparedness` gap detection — what counts as a gap (0 available, low capacity, out of service)
- [ ] Fire-behavior-aware gaps — intensity thresholds from NWCG cross-referenced if `fire_behavior_summary` provided
- [ ] Backward compatible — `resource_inventory=None` still works (returns empty/error from tools gracefully)
- [ ] `pytest tests/resources/ tests/tools/ -v`
