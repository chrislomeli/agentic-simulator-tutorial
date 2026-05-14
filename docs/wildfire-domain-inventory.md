# `src/domains/wildfire/` — Inventory and Status

## Overview

The wildfire domain has two distinct roles:

1. **Build-time tooling** (`world_builder/`) — one-shot scripts that pull real-world GIS data and write JSON or seed the DB. Not imported by the running application.
2. **Runtime simulation** — the Python modules the engine, sensors, and agents use every tick.

The JSON files in `scenario_data/` are the current bridge between the two. The goal is to eliminate runtime JSON reads and get everything from the DB instead.

---

## Runtime modules (used by the live application)

| File | Role | Status |
|---|---|---|
| `cell_state.py` | `FireCellState` — per-cell Pydantic model: terrain, fuel, fire, per-cell weather | ✅ Active |
| `environment.py` | `FireEnvironmentState` — macro weather driver; `wind_vector()` still used by `SimpleFirePhysicsModule` | ✅ Active (macro wind only) |
| `fuel_models.py` | `FuelModel` + `FUEL_MODELS` dict — Rothermel fuel parameters per `TerrainType` | ✅ Active |
| `physics.py` | `SimpleFirePhysicsModule` / `FirePhysicsModule` alias — heuristic probabilistic spread | ✅ Active (legacy fallback) |
| `rothermel_physics.py` | `RothermelFirePhysicsModule` — physics-based spread (Rothermel 1972); default in production | ✅ Active (primary) |
| `sampler.py` | `sample_local_conditions()` / `sample_thermal_region()` — bridge from engine grid to sensor `read()` | ✅ Active |
| `sensors.py` | Six sensor classes: `TemperatureSensor`, `HumiditySensor`, `WindSensor`, `SmokeSensor`, `BarometricSensor`, `ThermalCameraSensor` | ✅ Active |
| `nwcg_resources.py` | `NWCGResourceSpec` catalog + `suppression_category()` — NWCG resource typing and intensity thresholds | ✅ Active |
| `scenario_loader.py` | `load_scenario_from_json()` / `load_scenario_from_package()` — reads a JSON scenario file, loads terrain + sensors from DB, builds engine | ⚠️ Active but JSON-dependent (see below) |
| `scenarios.py` | `create_basic_wildfire()` / `create_full_wildfire_scenario()` / `create_wildfire_resources()` — hand-coded in-memory scenarios with no JSON | ✅ Active (JSON-free) |
| `__init__.py` | Re-exports the full public API for `from domains.wildfire import …` | ✅ Active |

---

## Build-time / data-gathering only (`world_builder/`)

Everything in this sub-package is **run once offline** to produce DB rows or JSON files. The running simulation never imports it.

| File | Role |
|---|---|
| `world_builder/__init__.py` | Exports build-time API (`TerrainCalibration`, `RegionProfile`, RAWS helpers, LANDFIRE helpers) |
| `world_builder/calibrations.py` | Maps LANDFIRE raster codes → `TerrainType`; reads `data/calibrations/*.json` |
| `world_builder/regions.py` | `RegionProfile` — bounding box, grid dimensions, cluster scheme, RAWS list; reads `data/regions/*.json` |
| `world_builder/raws.py` | `RawsStation` / `PlacedRawsStation` — RAWS lat/lon → grid cell snapping |
| `world_builder/landfire.py` | `load_fuel_grid()` / `aggregate_to_sim_grid()` — aggregates 30 m LANDFIRE TIFFs into sim-grid cells |
| `world_builder/cli/build_fuel_grid.py` | CLI: LANDFIRE TIFFs → `landfire/{region}/fuel_grid.json` |
| `world_builder/cli/build_scenario.py` | CLI: fuel grid + region profile → `scenario_data/{region}.json` |
| `world_builder/cli/fetch_raws_stations.py` | CLI: Synoptic API → verifies RAWS station list |
| `world_builder/data/calibrations/` | Per-ecosystem terrain mapping JSON (e.g. `california.json`) |
| `world_builder/data/regions/` | Per-region definition JSON (e.g. `lpnf-south.json`) |

---

## JSON — eliminated ✅

No JSON files remain in `src/`. All scenario data now comes from the DB.

- `scenario_data/` and `world_builder/` have been removed from `src/domains/wildfire/`.
- Copies live in `scripts/data_wrangling/` for reference and future build runs.
- `scenario_loader.py` was rewritten as `load_scenario_from_db()` — derives grid dimensions from DB row count, reads physics from `TerrainConfig`, accepts `ignition_points` as a parameter.
- `load_scenario_from_package()` is kept as a thin wrapper for call-site compatibility.
- Eval fixtures (`eval_calm_day.json`, `eval_obvious_fire.json`, `eval_resource_gap.json`, `test_coverage_scenarios.json`) are in `scripts/data_wrangling/scenario_data/` if needed for future test work.

---

## Dependency on `scenarios.py` vs `scenario_loader.py`

| Path | JSON? | DB? | Used by |
|---|---|---|---|
| `create_basic_wildfire()` in `scenarios.py` | ❌ No | ❌ No | Unit tests, quick demos |
| `load_scenario_from_db()` in `scenario_loader.py` | ❌ No | ✅ Yes | `main.py` (production entry point) |
