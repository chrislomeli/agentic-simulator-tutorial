# 10 — Evaluation (Ground Truth vs. Agent Assessment)

## Teaching goal
Student can score an agent's preparedness assessment against ground truth and understand why this evaluation approach works when fire prediction doesn't.

## I/O
- In: supervisor `result` dict + `resources.readiness_summary()` (ground truth) + `engine.history`
- Out: evaluation scores across 4 dimensions; comparison table across scenarios
- No new source files — `PreparednessEvaluator` is a self-contained script

## Must cover
- [ ] Why not binary prediction accuracy — "fire will happen" is unevaluable without a real ML model
- [ ] The 4 evaluation dimensions: gap detection accuracy, assessment completeness, command appropriateness, confidence calibration
- [ ] Gap detection: compare `actual_gaps` (from `readiness_summary`) to mentions in `situation_summary`
- [ ] Command appropriateness: did escalate commands correspond to actual critical gaps?
- [ ] Stub vs. LLM mode comparison — stub scores low on gap detection (expected), LLM should score high
- [ ] `engine.history` as context for assessment quality — sensor readings should match fire state
- [ ] False positive cost vs. false negative cost — for preparedness, false negatives (missed gaps) are worse
