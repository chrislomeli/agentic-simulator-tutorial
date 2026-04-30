# 09 — Scenario Knobs (Resilience Testing)

## Teaching goal
Student runs controlled degradation experiments and sees that preparedness assessment is still useful — and evaluable — even when conditions degrade.

## I/O
- In: same pipeline as Session 8, but with `resources.disable_resources(...)` or `inventory.thin_sensors(...)` applied before running
- Out: supervisor assessments across 3–4 scenarios with same random seed; `readiness_summary()` as ground truth
- No new source files — uses existing knobs

## Must cover
- [ ] Resource knobs: `reduce_resources(type, keep_fraction)`, `disable_resources(type, fraction)`, `reset_all()`
- [ ] Sensor knobs: `thin_sensors(keep_fraction)`, `inject_failures(failure_rate)`, `reset_all()`
- [ ] Same random seed = same fire conditions across all scenarios (controlled experiment)
- [ ] The 4-scenario matrix: baseline / blind spots / under-resourced / worst case
- [ ] Stub mode: gaps appear in `readiness_summary()` ground truth but supervisor doesn't detect them (no LLM)
- [ ] LLM mode: supervisor should detect gaps and escalate appropriately
- [ ] Preparedness framing: false positives are caution, missed gaps are failures — conservative bias is correct
- [ ] `resources.reset_all()` between scenarios
