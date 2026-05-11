# Validation milestone

Before building components A, B, or C, the foundation must prove itself empirically. This is a *milestone*, not a feature.

## Why this comes first

Today the wired sampler in `RuntimeOrchestrator` is `default_sampler`, which never consults cell fire state. Sensors emit elevated values regardless of whether anything is burning (the default sampler adds a hardcoded offset to ambient temperature and wind, then returns terrain attributes).

A fire-aware sampler — `domains.wildfire.sampler.sample_local_conditions` — already exists and reads `own_fire_intensity`, sums `neighbor_fire_heat`, and emits a `nearby_fire_cells` list with per-cell distances. It is not currently wired in.

Building potential scoring, aggregation, or sufficiency reasoning on top of the current sampler would be building on sand. The fire-aware sampler must be wired *and* the resulting stream verified before downstream work is safe to start.

## Steps

1. **~~Flip the sampler.~~ Done.** `main.py` now passes `sample_local_conditions` to `RuntimeOrchestrator` at construction time. No further code change required.
2. **~~Author validation scenario.~~ Done.** `domains/wildfire/scenario_data/lpnf-corridor-to-coast.json` extends the `lpnf-south` baseline with hot/dry/windy environment + a single ignition at (row=8, col=32) in the NE interior GRASSLAND. Companion narrative in `lpnf-corridor-to-coast.md` documents hypothesis and expected observations.
3. **Switch the loaded scenario in `main.py`.** Change line 132 from
   `engine, sensor_inventory, _ = load_scenario_from_package("lpnf-south")`
   to
   `engine, sensor_inventory, _ = load_scenario_from_package("lpnf-corridor-to-coast")`.
   This is a temporary swap for validation. Revert when the milestone passes.
4. **Increase `SMOKE_TICKS`.** The current value is 1 (smoke-test cadence). For validation, set it to 30 or more so Rothermel spread has time to play out. ~5 min per tick × 30 ticks = ~2.5 sim hours.
5. **Run `python main.py`.** Capture the sensor stream and the engine's `history` snapshots.
6. **Inspect** per the criteria in the scenario's companion `lpnf-corridor-to-coast.md` — specifically the "Expected observations" and "Pass / fail criteria" sections.
7. **Write a one-page observation note.** What the run produced, what was expected, what was observed, what (if anything) surprised. This is the milestone deliverable.

## Pass criteria

- Sensor readings near the ignition trend upward over ticks; readings far from the ignition do not.
- The trend is *plausible*, not necessarily realistic — order of magnitude is fine for now.
- Anomalies are explainable. (If a sensor far away spikes for no reason, find out why before declaring success.)

## Fail criteria

If the data does not show the expected trend, **stop**. Do not build A, B, or C until the foundation is honest. Investigate, in order:

1. The sampler — is it actually being called? Is it returning the expected fields?
2. The sensor `read()` implementations — are they consuming the fire-aware fields, or only the environment fields?
3. The engine state — is Rothermel actually advancing the fire? Check `engine.history`.

## Out of scope for this milestone

- Per-cell potential scoring.
- Cluster aggregation.
- Resource or historical lookups.
- Any agent-side reasoning quality.

This milestone is purely a foundation check. Reasoning quality is downstream.
