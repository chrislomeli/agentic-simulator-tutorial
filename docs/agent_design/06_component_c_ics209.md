# Component C — ICS-209 historical prior service

Given a profile of current conditions, returns historical percentiles for what similar fires actually required.

## The role this plays

This is what makes the agent's "we have enough / we don't" claim defensible rather than vibes. Without a historical anchor, sufficiency reduces to guessing. With one, the agent can say:

> Conditions match seven Kern County fires from 2019–2022 in CHAPARRAL on south slopes with sustained winds 15–25 mph. Those fires required peak personnel of 45–80 and 4–7 engines within 90 minutes. We have 3 engines on the deck with 5 more available via mutual aid in 60 minutes — **marginal**.

That kind of grounded analogy is what turns the agent from a scorer into a reasoner.

## Inputs

A profile dict describing the current conditions to match against:

```python
@dataclass(frozen=True)
class ConditionProfile:
    fuel_type: str               # CHAPARRAL, GRASSLAND, FOREST, ...
    terrain_class: str           # FLAT, ROLLING, STEEP, ...
    wind_band_mph: tuple[float, float]
    temp_band_c: tuple[float, float]
    humidity_band_pct: tuple[float, float]
    fuel_moisture_band: tuple[float, float]
    season: str                  # spring, summer, fall, winter
    geographic_unit: str | None = None  # e.g. CA forest unit, optional filter
```

## Outputs

```yaml
profile_match:
  similar_incidents: 7
  match_strategy: "fuel_type + season + wind_band + humidity_band"

peak_personnel:        { p25: 35, p50: 60, p75: 95 }
peak_engines:          { p25: 3,  p50: 5,  p75: 8 }
peak_dozers:           { p25: 1,  p50: 2,  p75: 4 }
peak_aircraft:         { p25: 0,  p50: 1,  p75: 2 }
final_size_acres:      { p25: 50, p50: 200, p75: 800 }
duration_hours:        { p25: 12, p50: 36,  p75: 96 }
containment_pct_24h:   { p25: 30, p50: 55, p75: 80 }
```

The `profile_match.similar_incidents` count is load-bearing — `n=7` and `n=70` should be weighted differently by the agent.

## Data sourcing (the long pole)

- **Source.** ICS-209-PLUS dataset (FEMA / NIFC public release) or NWCG SIT-209 archive.
- **Scope.** Regional + recent slice. California + neighboring states, 2018–present. Roughly 500–2000 incidents.
- **Storage.** Postgres table in the same database as terrain / sensors / resources.
- **Schema.** Keep only fields the matcher uses (above) plus `incident_id` and `incident_name` for traceability. Discard narrative fields.
- **Ingest.** A one-shot ETL script. Idempotent — safe to re-run as the source updates.

The ETL is the longest pole in this component. Plan for a day or two on data wrangling alone.

## Similarity matching

- **v1 (naive).** Filter by `fuel_type + season + binned_wind + binned_humidity`. Return the matching set; compute percentiles.
- **v2 (weighted).** Normalized feature distance with per-feature weights. Same interface.

The output's `match_strategy` field documents which approach was used so the agent (and humans reviewing reasoning) can interpret the percentiles correctly.

## Boundaries

- Knows about historical records only.
- Does not consult current state, current resources, or live sensors.
- Does not produce a recommendation — only percentile distributions.

## Integration point

A read-only Postgres-backed function. Two options for how the agent reaches it:

- **Pre-computed.** Assembler calls it per cluster, embeds the result in the bird's-eye payload. Deterministic, debuggable.
- **Tool.** Agent calls it dynamically with refined queries.

Recommendation: **pre-compute in v1**, expose as a tool in v2 once the agent's reasoning patterns are clearer. Lives at `src/agents/tools/ics209_priors.py` (proposed) — even when pre-computed, treating it as a tool-shaped function leaves the v2 path open without refactor.

## Open questions

- **What "similar" means for ICS-209.** Records describe response, not optimal response. A fire that burned 800 acres because it was *under-resourced* is in the dataset alongside one that burned 800 acres because conditions were extreme but resources were ample. The priors describe *what happened*, not *what should have happened*. Document this clearly so the agent doesn't treat percentiles as "ought."
- **Confidence on the match.** The output already includes `similar_incidents`. Should we also include a match-quality score (e.g., average feature distance)? Default: not in v1.
- **Geographic filter.** Whether to scope matches to a specific forest unit / GACC, or let the broader regional dataset speak. Lean broader for v1 — `n` is more important than locality at small dataset sizes.
- **ICS-209 data licensing and refresh.** Confirm public-domain status of the chosen source before committing to the schema.
