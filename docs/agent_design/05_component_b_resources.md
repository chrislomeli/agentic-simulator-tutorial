# Component B — Resource posture service

Per-cluster snapshot of available resources. Wraps `ResourceInventory`. No reasoning — just facts.

## Inputs

- `ResourceInventory` — the loaded scenario's resources.
- `cluster_id` — which cluster's posture is being snapshotted.

## Outputs

```yaml
cluster: cluster_north
local:
  engines: 3
  dozers: 1
  helitack: 0
  hand_crews: 1
  water_tenders: 2
  total_personnel: 32
mutual_aid:
  engines_within_60min: 5
  dozers_within_60min: 1
  helitack_within_120min: 1
staging:
  road_access_min: 15        # nearest road-accessible staging
  helo_access_min: null      # no helo staging applicable
seasonal_effects:
  units_offline: 0           # e.g. seasonal-only resources currently down
```

The exact field names should mirror what `ResourceInventory` and the underlying `resources` SQL table actually expose. Verify against `src/resources/` and `src/stores/sql/resources.sql` before locking the schema.

## What "mutual aid" means

The `lpf_interface_priority` and `mutual_aid_agreement` fields on the `resources` table imply mutual-aid relationships across clusters. The service uses those to compute the within-60min / within-120min counts.

First cut can be naive (count all mutual-aid resources from neighboring clusters). Refinement comes later if needed — agent reasoning quality will tell us whether more granularity is required.

## Boundaries

- Knows about `ResourceInventory` only.
- Does not consult risk, sensor state, or history.
- Does not score "is this enough" — it only counts.

## Integration point

Called by the assembler once per cluster agent invocation. Two options:

- **Free function** at `src/resources/posture.py` (proposed). Keeps `ResourceInventory` as a pure data structure.
- **Method on `ResourceInventory`** itself.

Lean toward the free function — it keeps the inventory minimal and the posture-derivation logic visible in its own module.

## Open questions

- **Availability semantics.** Should "available" account for resources currently committed to other incidents? Under our scope (no active incidents) the answer is no — every resource that exists is "available" unless the scenario JSON declares otherwise. Document this clearly in the docstring.
- **Distance computation.** Use grid distance × cell size, or use lat/lon haversine over the geo overlay? Lean haversine since the geo overlay is already stamped on every cell and matches reality. Grid distance would diverge in non-square cells.
- **Seasonal resources.** The `seasonal` field on the resources table may flip resources offline depending on date. The scenario JSON's `start_time` (or environment date) determines which resources count. Default: ignore seasonality in v1; revisit if it produces obviously wrong postures.
