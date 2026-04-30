# 08 — Full Pipeline (Everything Wired)

## Teaching goal
Student runs the complete system end-to-end for the first time and verifies all interfaces work together.

## I/O
- In: `create_full_wildfire_scenario()` → `engine` + `resources`
- Out: supervisor `situation_summary` and `pending_commands`, `engine.history`, `resources.readiness_summary()`
- No new source files — pure integration

## Must cover
- [ ] Full data flow: world engine → sensors → publisher → queue → consumer → cluster agents → supervisor → commands
- [ ] `random.seed(42)` — why a fixed seed (reproducibility for Sessions 9–10)
- [ ] Shared `InMemoryStore` — cluster agents and supervisor use the SAME store instance
- [ ] Async pipeline (publisher + consumer) runs first, THEN sync supervisor runs on accumulated findings
- [ ] Events enqueued = sensors × ticks (sanity check)
- [ ] Ground truth comparison: `engine.history[-1]` vs. supervisor assessment
- [ ] LangSmith trace structure — what each node looks like in the UI
- [ ] `pytest tests/ -v` — everything passes
