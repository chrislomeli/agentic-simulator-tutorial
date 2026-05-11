# Component A — Potential heatmap service

Per-cell potential scoring and per-cluster aggregation. Deterministic. No agent involvement.

## Inputs

- `GenericWorldEngine[FireCellState]` — current grid + environment state.
- `SensorInventory` — for cluster membership lookups when aggregating.
- (Optionally) recent sensor stream summary if recent readings inform potential beyond static state. Default: no — see open questions.

## Outputs

### Per-cell scores

A 2D structure (sparse dict or array) keyed by `(row, col, layer)`:

```python
@dataclass(frozen=True)
class CellPotential:
    cell_key: str            # "row,col,layer"
    score: float             # 0.0 – 1.0
    components: dict[str, float]
    # transparency: {"fuel": 0.7, "moisture_dryness": 0.6, "slope": 0.3,
    #                "temp": 0.8, "humidity_dryness": 0.7, "wind": 0.5}
```

The `components` dict is non-negotiable — without it the score is a black box and the agent (or a human reviewer) cannot explain its reasoning.

### Per-cluster aggregate

```yaml
cluster: cluster_north
area_acres: 4200
cells_extreme: 3       # potential >= 0.85
cells_high: 11         # 0.65 <= potential < 0.85
cells_moderate: 24     # 0.45 <= potential < 0.65
peak_potential: 0.91
hotspots:              # top N cells, configurable, default N = 5
  - { row: 7,  col: 12, score: 0.91, terrain: CHAPARRAL,
      slope: 0.32, fuel_moisture: 0.22 }
  - { row: 8,  col: 12, score: 0.88, ... }
terrain_mix: { CHAPARRAL: 0.52, GRASSLAND: 0.31, FOREST: 0.17 }
```

## Scoring approach

Open question — three viable options:

1. **NFDRS-style index** (Burning Index, Energy Release Component). Standard, defensible, well-understood. Requires implementing a few formulas and a fuel-model lookup.
2. **Weighted linear combination**: `fuel × (1 − moisture) × slope_factor × wind_factor × temp_factor × (1 − humidity_factor)`. Trivial to implement; calibration is by inspection.
3. **Learned scorer** trained on labeled fire-day data. Out of scope for v1.

Recommendation: **(2) for v1** with documented weights, **(1) as a v2 swap-in** once the rest of the pipeline is proven. The interface is the same either way — only the body of the scoring function changes.

## Boundaries

- Knows about engine state and grid only.
- Does not consult `ResourceInventory`.
- Does not consult ICS-209 or any historical record.
- Does not produce a verdict — only a score and its components.

## Integration point

Called by the assembler once per cluster agent invocation. Lives at `src/domains/wildfire/potential.py` (proposed). Pure function; no async, no I/O. Should be importable by the assembler without touching the orchestrator.

## Open questions

- **Sensor anomalies as input.** Should the heatmap incorporate live sensor anomalies (e.g., a temp spike), or restrict itself to static + environment factors? Default: no — the heatmap is a *condition* assessment, and live sensor anomalies are signals the agent reasons over separately. Mixing them obscures provenance.
- **Smoothing.** Gaussian smoothing across cells vs. raw cell scores. Default: raw. Smoothing is a presentation concern; if a viewer wants smoothed it can apply post-hoc.
- **Score range.** Continuous `[0, 1]` vs. discrete `low/moderate/high/extreme`. Continuous is more flexible; the discrete bucketing happens at aggregation time (see `cells_extreme`, `cells_high`, etc.).
- **Hotspot count `N`.** Default 5. Surface as a config knob, not a hard-coded value.
