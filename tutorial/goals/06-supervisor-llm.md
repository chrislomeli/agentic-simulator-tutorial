# 06 — Supervisor Agent (LLM Mode)

## Teaching goal
Student adds an LLM to the supervisor with two separate ReAct phases — assess, then decide — and understands why two phases is better than one.

## I/O
- In: same `SupervisorState` as Session 5
- Out: `situation_summary` (natural language) and `pending_commands` (structured `ActuatorCommand` list)
- Files created: `src/tools/supervisor_tools.py`
- Files modified: `src/agents/supervisor/graph.py`

## Must cover
- [ ] Two ReAct loops, not one: `assess_situation_llm` (what happened?) → `decide_actions_llm` (what to do?)
- [ ] Why two loops: prevents premature action; assessment anchors the decision
- [ ] `_SupervisorToolState` shared state holder — all supervisor tools read from it; loaded once per invocation
- [ ] The four supervisor tools: `get_all_findings`, `get_finding_summary`, `check_cross_cluster`, `get_cluster_finding_history`
- [ ] `get_cluster_finding_history` reads from the LangGraph Store (written by cluster agents in Session 2)
- [ ] Structured output for commands: `ActuatorCommand` with `command_type`, `cluster_id`, `priority`, `payload`
- [ ] `pytest tests/agents/test_supervisor.py tests/tools/ -v`
