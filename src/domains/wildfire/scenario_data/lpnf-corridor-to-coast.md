# lpnf-corridor-to-coast

Companion narrative for `lpnf-corridor-to-coast.json`. The engine never reads this file. Humans use it for review; the agent may receive it as reasoning context.

## Hypothesis

Under hot, dry, windy conditions with a 45° wind (from NE blowing toward SW) and an ignition in the NE interior GRASSLAND, Rothermel propagation should drive the fire south-west through a continuous fuel bed. Sensors arranged across the SW-bound path should register increasing thermal and decreasing humidity readings over ticks, in approximate order of their distance from the ignition along the wind vector.

## Stakes (sufficiency-side context)

The fire's downwind path leads toward the **Carpinteria-side urban interface** at rows 38–40, cols 3–11 — a contiguous URBAN cluster on the south coast. At cell-size 6336 ft and realistic chaparral spread rates under 11 m/s wind, the urban edge is far enough away that the fire will not reach it during a short validation run; that is fine. The validation milestone only checks signal propagation, not impact.

For *sufficiency reasoning* (downstream components B/C), the relevant stakes are:

- **Primary asset at risk**: Carpinteria coastal urban cluster (~30 cells downwind of ignition).
- **Secondary asset at risk**: Coastal community sensors in `cluster-sb-coast` (rows 33–40, cols 5–18).
- **Cluster of focus**: `cluster-sb-coast` is the receiving cluster; `cluster-interior` is the source.

The agent should not penalize potential scoring for proximity to urban — stakes are an input to the *sufficiency* call, not the per-cell potential score. (See `01_scope.md` and `02_architecture.md`.)

## Scenario shape

| Field | Value | Notes |
|---|---|---|
| Grid | 50 × 50 | Inherited from `lpnf-south` |
| Cell size | 6336 ft (~1.2 mi) | Inherited |
| Bounds | LPNF South | Inherited |
| Wind | 11 m/s from 45° (NE → SW) | 8 m/s baseline → 11 m/s here |
| Temperature | 38 °C | 30 °C baseline |
| Humidity | 12 % | 25 % baseline |
| Default fuel moisture | 0.08 | 0.12 baseline (drier) |
| Ignition | (row=8, col=32) intensity 0.85 | Single point in continuous GRASSLAND |
| Resources | none added (yet) | Component B integration adds these later |

## Why ignition is at (8, 32)

- **Fuel continuity downwind.** From (8, 32) the SW path crosses a contiguous SCRUB+GRASSLAND bed for ~30 cells before encountering the coastal WATER edge.
- **Sensor coverage downwind.** `cluster-sb-coast` sensors sit between rows 33–40 and cols 5–18, well within the wind-driven path. They should register the propagating signal.
- **Distant from boundaries.** The cell is far enough from grid edges that early-tick spread is contained within the engine's known region.

## Expected observations during validation

Run with the fire-aware sampler (`sample_local_conditions`) wired into `RuntimeOrchestrator` (already done in `main.py`). Suggested run: 30+ ticks at the existing 5 min/tick cadence (~2.5 sim hours).

What to look for:

1. **At t=0** the cell at (8, 32) is BURNING (visible in `engine.history[0].grid_summary`).
2. **Within a few ticks**, neighboring cells in the SW direction begin to ignite (Rothermel-driven). Confirm via successive `engine.history[t].grid_summary["BURNING"]` counts increasing.
3. **Sensors in `cluster-cuyama` and `cluster-interior` near the ignition** should show:
   - `temperature_c` readings elevated above the 38 °C ambient.
   - `humidity_pct` readings depressed below 12 %.
   - `smoke` readings (if smoke sensors are present) rising over time.
4. **Sensors in `cluster-sb-coast`** should show baseline-only behavior in the early ticks (fire hasn't reached them) and progressively rising signals as ticks advance, *if* the run is long enough for the spread to reach their neighborhood.
5. **Sensors far from the ignition path** (e.g., `cluster-ventura-east`) should remain at baseline throughout — no spurious activation.

## Pass / fail criteria

**Pass**: Sensors near the ignition trend upward; sensors distant from the ignition do not. Anomalies (if any) are explainable from the data.

**Fail**: Sensors far from the ignition spike inexplicably, OR sensors near the ignition show no trend, OR the engine reports no spread despite Rothermel being active. In any fail mode, *do not proceed* to component A — investigate the sampler, the sensor `read()` implementations, and the engine state until the trend is honest.

## Open issues, intentionally deferred

- No resources are declared. The validation milestone does not need them; component B integration will add a cluster-sb-coast staging set in a follow-up.
- No sensor faults. Failure-mode mechanics are out of scope for this milestone (and probably for the project per `01_scope.md`).
- Run length is left to the runner (`SMOKE_TICKS` in `main.py`). Validation observations should specify what tick count was used.
