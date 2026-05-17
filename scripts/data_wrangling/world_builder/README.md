# world_builder

Build-time package that converts real-world GIS and sensor data into wildfire simulation scenario files.

> **Important**: This package is build-time only. The runtime simulator does not import from here—it reads the generated scenario JSON files directly.

## Pipeline Overview

```
LANDFIRE GeoTIFFs ──► build-fuel-grid ──► landfire/{region}/fuel_grid.json
                                                     │
Synoptic API        ──► fetch-raws-stations ────────┤
                                                     │
region_data JSON ────────────────────────────────────┤
                                                     ▼
                                            build-scenario
                                                     │
                                                     ▼
                                          scenario_data/{region}.json
```

## CLI Commands

Three CLI entry points (defined in `pyproject.toml`):

| Command | Purpose |
|---------|---------|
| `build-fuel-grid` | Convert LANDFIRE TIFFs → fuel_grid.json |
| `build-scenario` | Combine fuel_grid + region profile → scenario JSON |
| `fetch-raws-stations` | Verify RAWS stations via Synoptic API |

## Quick Start

### 1. Build a fuel grid from LANDFIRE data

```bash
build-fuel-grid --region lpnf-south
```

This reads LANDFIRE GeoTIFFs (FBFM40 fuel models, EVT vegetation, canopy cover) and creates a JSON grid of fuel cells at `scenario_data/landfire/lpnf-south/fuel_grid.json`.

### 2. Build the scenario

```bash
build-scenario --region lpnf-south
```

This combines the fuel grid with the region's RAWS station inventory to produce `scenario_data/lpnf-south.json`, ready for the simulator.

## Package Structure

```
world_builder/
├── __init__.py           # Public API exports
├── calibrations.py       # TerrainCalibration: LANDFIRE → TerrainType mappings
├── landfire.py           # Fuel grid loading & aggregation to sim grid
├── raws.py               # RAWS station schema & grid placement
├── regions.py            # RegionProfile: bbox, grid, clusters, stations
├── cli/
│   ├── build_fuel_grid.py      # TIFF extraction CLI
│   ├── build_scenario.py       # Scenario assembly CLI
│   └── fetch_raws_stations.py  # Synoptic API verification CLI
└── data/
    ├── calibrations/     # Per-ecosystem terrain mappings (JSON)
    └── regions/          # Region definitions (JSON)
```

## Core Concepts

### TerrainCalibration (`calibrations.py`)

Maps LANDFIRE raster codes to simulator terrain types. Each calibration defines:
- FBFM40 fuel model → TerrainType mapping
- EVT vegetation type → TerrainType fallback mapping
- Canopy cover % → vegetation density formula
- Per-terrain fuel moisture defaults

**Available calibrations**: `california` (Mediterranean chaparral)

```python
from domains.wildfire.world_builder import get_calibration, CALIFORNIA_CALIBRATION

cal = get_calibration("california")
terrain = cal.resolve_terrain(fuel_codes=[101, 102], evt_codes=[7493])
veg_density = cal.canopy_to_vegetation(canopy_cover=45.0)
```

### RegionProfile (`regions.py`)

Groups all configuration needed for one geographic region:
- Bounding box (lat/lon limits)
- Grid dimensions (rows × cols)
- Cluster scheme for sensor organization
- RAWS station inventory
- Reference to TerrainCalibration

```python
from domains.wildfire.world_builder import get_region

region = get_region("lpnf-south")
print(region.bounds)           # {'lat_min': 34.4, 'lat_max': 34.8, ...}
print(region.grid_rows)        # 40
print(region.raws_stations)    # tuple of RawsStation objects
```

### Fuel Grid Aggregation (`landfire.py`)

LANDFIRE cells are ~30m resolution. Simulator grids are coarser. `aggregate_to_sim_grid()` buckets fine LANDFIRE cells into sim cells and resolves terrain using a calibration:

```python
from domains.wildfire.world_builder import (
    load_fuel_grid, aggregate_to_sim_grid, get_region
)

region = get_region("lpnf-south")
fuel_cells = load_fuel_grid(region.fuel_grid_path)
terrain_map = aggregate_to_sim_grid(
    fuel_cells,
    grid_rows=region.grid_rows,
    grid_cols=region.grid_cols,
    bounds=region.bounds,
    calibration=region.calibration,
)
# terrain_map: dict[(row, col, layer), SimCellTerrain]
```

### RAWS Station Placement (`raws.py`)

RAWS stations are snapped to sim-grid cells using lat/lon → grid conversion:

```python
from domains.wildfire.world_builder import place_raws_on_grid, get_region

region = get_region("lpnf-south")
placed = place_raws_on_grid(
    region.raws_stations,
    grid_rows=region.grid_rows,
    grid_cols=region.grid_cols,
    bounds=region.bounds,
)
# placed: list of PlacedRawsStation with (row, col) assigned
```

## Adding a New Region

1. **Create calibration** (if new ecosystem):
   ```bash
   # Create data/calibrations/rocky-mountain.json
   # Follow the schema from data/calibrations/california.json
   ```

2. **Create region definition**:
   ```bash
   # Create data/regions/my-region.json
   # Include: name, bounds, grid, clusters, raws_stations, calibration reference
   ```

3. **Build fuel grid**:
   ```bash
   build-fuel-grid --region my-region
   ```

4. **Build scenario**:
   ```bash
   build-scenario --region my-region
   ```

## Data Files

### Calibrations (`data/calibrations/`)

JSON files defining per-ecosystem mappings:

```json
{
  "name": "california",
  "fbfm40_to_terrain": {"101": "CHAPARRAL", "102": "FOREST", ...},
  "evt_to_terrain": {"7493": "CHAPARRAL", ...},
  "canopy": {"baseline": 0.1, "none_default": 0.3},
  "fuel_moisture_by_terrain": {"CHAPARRAL": 0.08, "FOREST": 0.12, ...}
}
```

### Regions (`data/regions/`)

JSON files defining specific simulation areas:

```json
{
  "name": "lpnf-south",
  "display_name": "Los Padres NF (South)",
  "bounds": {"lat_min": 34.4, "lat_max": 34.8, "lon_min": -119.9, "lon_max": -119.4},
  "grid": {"rows": 40, "cols": 40},
  "clusters": ["coastal", "inland", "ridge"],
  "raws_stations": [...],
  "calibration": "california"
}
```

## Public API

```python
from domains.wildfire.world_builder import (
    # Calibration
    TerrainCalibration,
    CALIBRATIONS,
    CALIFORNIA_CALIBRATION,
    get_calibration,
    
    # Regions
    RegionProfile,
    REGIONS,
    get_region,
    
    # RAWS
    RawsStation,
    PlacedRawsStation,
    place_raws_on_grid,
    
    # LANDFIRE
    FuelGridCell,
    SimCellTerrain,
    load_fuel_grid,
    aggregate_to_sim_grid,
)
```

## References

- **LANDFIRE**: https://landfire.gov
- **FBFM40 Fuel Models**: https://www.fs.usda.gov/rm/pubs/rmrs_gtr153.pdf
- **EVT (Existing Vegetation Type)**: https://landfire.gov/evt.php
- **RAWS/Synoptic API**: https://synopticdata.com
