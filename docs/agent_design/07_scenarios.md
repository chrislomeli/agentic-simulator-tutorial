# Scenario library

Scenarios are *snapshots of conditions* (per `01_scope.md`). The agent reasons about a moment; it does not track or predict. The library exists so that potential and sufficiency reasoning can be exercised against a deliberate spread of cases.

## Existing scenarios (audit)

| File | Grid | Cell size | Bounds | Has ignition | Has resources | Purpose |
|---|---|---|---|---|---|---|
| `lpnf-south.json` | 50 × 50 | 6336 ft | LPNF South | no | no | **Geographic baseline.** Real LPNF terrain + sensor placement across four clusters (cuyama, interior, sb-coast, ventura-east). The world map. |
| `north_south_fire.json` | 20 × 20 | 200 ft | none | no | yes (10) | Small dev/test scenario. Different scale from lpnf-south. |
| `eval_obvious_fire.json` | 10 × 10 | 200 ft | none | yes | yes (5) | Eval fixture: clear hotspot, sufficient resources. |
| `eval_calm_day.json` | 10 × 10 | 200 ft | none | no | yes (5) | Eval fixture: negative control. |
| `eval_resource_gap.json` | 10 × 10 | 200 ft | none | yes | yes (5) | Eval fixture: same fire as obvious_fire, resources moved away. |

## Reading the audit

- `lpnf-south.json` is the *geography*, not a runnable scenario. It has no ignitions and no resources. `main.py` loads it directly today, which is why nothing in the simulation produces fire signal.
- The `eval_*` and `north_south_fire` scenarios are at a 200 ft cell size — that's a different *scale of world* from lpnf-south's 6336 ft cells. They are not derivatives of the lpnf-south baseline; they are independent small-scale fixtures for unit-test-style evaluation.
- **There is no scenario today that runs on the lpnf-south geography with an ignition and resources.** That gap is what the validation milestone (`03_validation.md`) needs filled.

## Geographic context (lpnf-south baseline)

Verified by inspecting cell data:

- Row 0 = north (lat 35.15), Row 49 = south (lat 34.25).
- Col 0 = west (lon −119.95), Col 49 = east (lon −118.45).
- Pacific coastline runs along the south/southwest edge (rows 41–48, cols 0–15: contiguous WATER).
- **URBAN clusters** (the WUI exposure points):
  - Carpinteria-side coastal cluster: rows 38–40, cols 3–11.
  - Eastern coastal cluster (Ventura/Oxnard side): rows 39–43, cols 45–48.
  - Scattered: row 16 col 25, row 49 cols 31 and 48.
- **Continuous fuel beds** (SCRUB + GRASSLAND): the central interior, rows 0–25 cols 10–40, is an extensive contiguous fuel zone.
- **Default wind direction**: 45° (from NE, blowing toward SW). This already aligns prevailing wind toward the Carpinteria-side urban edge.

This geography is *already designed* for "interior ignition propagates downwind toward urban interface." Scenarios on this baseline should exploit that.

## Scenario library — design forward

### Authoring problem

Authoring scenarios on top of `lpnf-south.json` requires either copying its 2417 cell entries (terrain + sensors) into a new file, or referencing the baseline by inheritance. The former is a maintenance disaster — every edit to `lpnf-south.json` must propagate by hand.

### Proposed pattern: scenario inheritance

Add an `extends:` field to scenario JSON. A derivative scenario looks like:

```json
{
  "name": "lpnf-corridor-to-coast",
  "extends": "lpnf-south",
  "description": "Hot/dry/windy day. Ignition in NE interior. Wind drives fire SW through continuous fuel toward Carpinteria-side urban interface.",
  "environment": {
    "temperature_c": 38.0,
    "humidity_pct": 12.0,
    "wind_speed_mps": 11.0,
    "wind_direction_deg": 45.0
  },
  "ignition": [
    { "row": 8, "col": 32, "intensity": 0.8 }
  ],
  "cells": {
    "30,8": { "resources": [ ... ] }
  }
}
```

Loader merge semantics:

| Field | Merge rule |
|---|---|
| `dimensions`, `bounds`, `physics`, `defaults` | derivative overrides base entirely |
| `environment` | shallow merge; derivative keys win |
| `cells` | union by key; derivative cells override base entries with the same key |
| `ignition` | append (derivative ignitions add to any in base) |
| `name`, `description` | derivative overrides |

This is a small surgical change to `scenario_loader.py` and unblocks the entire scenario library forever. Implementation gated on user approval.

### Library plan (when inheritance is in)

| Filename | Extends | Hypothesis | Built when |
|---|---|---|---|
| `lpnf-corridor-to-coast.json` | `lpnf-south` | Hot/dry/windy, ignition in NE interior, wind drives fire SW through fuel toward Carpinteria urban edge. Validation target + canonical high-potential case. Companion `.md` documents WUI stakes. | **Now** (validation milestone) |
| `lpnf-mild-baseline.json` | `lpnf-south` | Mild day, no ignition. Negative control: per-cell potential should be Low everywhere, sufficiency Sufficient. | Component A |
| `lpnf-multi-corridor.json` | `lpnf-south` | Two ignitions, two clusters affected. Tests cluster differentiation and supervisor regional rollup. | Component A |
| `lpnf-corridor-away-from-urban.json` | `lpnf-south` | Same fuel/weather as corridor-to-coast, ignition in interior such that wind drives fire away from urban edge (toward more interior). Sufficiency contrast: same potential, lower stakes. | Component C |
| `lpnf-regional-extreme.json` | `lpnf-south` | Sustained Diablo wind event + extreme fuel dryness, ignition in any of several clusters, resources scaled down to mutual-aid only. Sufficiency call: Insufficient. | Component C |

Each scenario gets a **companion markdown** (`<scenario>.md` next to `<scenario>.json`) documenting:

- **Hypothesis**: what this scenario tests (e.g., "potential High along corridor; sufficiency Marginal due to WUI exposure").
- **Stakes**: what's at risk if the worst plausible fire develops (e.g., "Carpinteria urban interface within ~25 grid-cells of ignition").
- **Expected observations**: what the validation/eval should see in the data.

The engine never reads the markdown. The agent may receive it as reasoning context; humans use it for review.

## Naming convention

- `lpnf-*.json` — scenarios on the `lpnf-south` baseline geography.
- `eval_*.json` — micro-fixtures for unit-test-style evaluation. Keep separate from the lpnf-* library.
- `<region>-<descriptor>.json` for any future region.

## What is locked

- The library is **derivative**. Real scenarios extend `lpnf-south`; they don't duplicate its terrain.
- Companion markdown per scenario is **mandatory** — narrative/stakes/hypothesis lives there, not in the JSON.
- Stakes (urban exposure, asset risk) is a **sufficiency-side** concern. Per-cell potential never reads stakes.

## Decisions made

- **`extends:` loader change is in.** Implemented in `scenario_loader.py` via `_resolve_extends` and `_merge_scenarios`. Sanity-tested. Existing scenarios without `extends` are passed through unchanged.
- **Markdown companions live next to JSON.** `<scenario>.md` sits beside `<scenario>.json` in `scenario_data/`. Engine never reads the markdown.
- **Eval fixtures left alone.** `eval_*` and `north_south_fire` predate this plan and serve a different purpose. They are not derivatives of `lpnf-south` and will not be retrofitted.

## Status

- `lpnf-corridor-to-coast.json` + `.md` — **authored.** Validation target. Extends `lpnf-south`.
- All other scenarios in the library plan above — **deferred** until their consuming component is being built.
