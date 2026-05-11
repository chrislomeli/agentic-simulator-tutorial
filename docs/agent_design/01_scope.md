# Scope

The agent answers two questions about a moment in time.

1. **What is the fire potential here?** Given current fuel, weather, terrain, and sensor signals, how primed is the landscape to burn? Not "is there a fire" — *how dangerous is the state*.
2. **Best/worst resource bracket.** If the worst plausible fire developed under these conditions, do we have enough resources? Three buckets are sufficient: `sufficient` / `marginal` / `insufficient`.

## In scope

- Per-cell and per-cluster potential scoring driven by static terrain + dynamic environment + live sensor signals.
- Resource posture snapshot per cluster (engines, dozers, aircraft on the deck; staging distances; mutual-aid lookahead).
- Historical priors from ICS-209 records — "fires under similar conditions historically required X."
- Synthesis by the cluster agent (per-cluster verdict) and supervisor (regional rollup with a sufficiency call).
- Spread modeling used as a *projection* tool ("if it ignited at this cell right now, worst-plausible footprint?") feeding sufficiency reasoning.

## Out of scope

- Active fire tracking or growth observation.
- Multi-incident triage or dispatch.
- Predicting where a fire will go or when.
- Diagnosing whether a sensor anomaly is a real fire vs. equipment fault.
- Timed event sequences within a scenario (extra ignitions at tick N, weather shifts, scheduled sensor faults).
- Distractor classification.

## Scope test

When proposing a feature, ask: *does this serve potential assessment or sufficiency bracketing?* If neither, it's out.
