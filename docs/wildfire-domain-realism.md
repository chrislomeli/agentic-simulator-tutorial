# Wildfire Domain Realism — Design Decisions and Upgrade Path

This document covers three things for anyone working on or demoing this project:

1. How closely the wildfire simulation maps to real operational systems (NFDRS, FEMS)
2. Which simplifications are conscious tradeoffs and why they are acceptable
3. What can be upgraded later — and why the current architecture supports those upgrades without touching agent code

---

## How This Maps to Real Systems

### NFDRS (National Fire Danger Rating System)

NFDRS is the operational system used by USFS/BLM/NPS to produce daily fire danger ratings (Low through Extreme) from fuel moisture, weather, and fuel model inputs.

| NFDRS Component | Project Equivalent | Notes |
|---|---|---|
| Fuel model input (20 models) | `TerrainType` → `FuelModel` lookup (4 types) | Simplified; see tradeoffs below |
| Fuel moisture (4 timelag classes) | Single `fuel_moisture` float per cell | Simplified |
| Spread Component (SC) | `avg_ros_ft_min` in summarize() | Same concept, different formula path |
| Burning Index (BI) | `danger_rating` string (Low/Moderate/.../Extreme) | Labels match NFDRS; formula is approximated |
| Energy Release Component (ERC) | Not computed | Not needed for agent decision logic |
| Ignition Component (IC) | Not computed | Not needed for agent decision logic |
| Weather input | `FireEnvironmentState` (temp, RH, wind) | Correct inputs; real NFDRS consumes NWS gridded forecasts |

### FEMS (Fire Environment Mapping System)

FEMS is an operational mapping tool used by USFS/BLM to produce spatially distributed fire environment layers from fuel maps and weather.

| FEMS Component | Project Equivalent | Notes |
|---|---|---|
| Fuel maps (LANDFIRE, 40 Scott-Burgan models) | `GenericTerrainGrid` with `TerrainType` per cell | Structural match; fewer fuel types |
| Spatially distributed weather | Single global `FireEnvironmentState` | Real FEMS is spatially distributed at ~2.5 km |
| Fire spread model (Rothermel via FARSITE) | `RothermelFirePhysicsModule` | Same Rothermel (1972) core, approximated (see below) |
| Fireline intensity (Byram 1959) | `fireline_intensity_btu_ft_s` on `FireCellState` | Same formula and units |
| Resource typing thresholds | `INTENSITY_THRESHOLDS` in `nwcg_resources.py` | Directly matches NWCG IRPG operational guidelines |

**Overall assessment:** The agent decision vocabulary (BTU/ft/s thresholds, NWCG resource IDs, danger rating tiers, flame length, ROS in ft/min) is accurate. The simplifications are in physics inputs, not outputs.

---

## Where Data Really Comes From in Real Operations

The current project models all environmental inputs as ground sensors. In real NFDRS/FEMS deployments, data comes from five distinct source types:

### 1. RAWS — Remote Automated Weather Stations
Physical ground stations (~2,200 across the US, managed by USFS/BLM/NPS). Report temperature, RH, wind speed/direction, precipitation, solar radiation, and fuel stick moisture every 10–60 minutes.

**Maps to:** `TemperatureSensor`, `HumiditySensor`, `WindSensor`, `BarometricSensor`

**Key difference:** RAWS are sparse — roughly one station per 50–100 square miles. The project places sensors on many grid cells, which is much denser than reality.

### 2. LANDFIRE — Fuel and Vegetation Maps
A static GIS database maintained by USFS/USGS, updated roughly every 2 years via satellite imagery, field sampling, and modeling. Provides fuel model assignment, canopy cover, canopy height, canopy base height, canopy bulk density, slope, aspect, and elevation at 30-meter raster resolution.

**Maps to:** `FireCellState` fields (`terrain_type`, `vegetation`, `slope`, `fuel_moisture` baseline)

**Key difference:** In real systems the fuel map is a pre-loaded static layer, not sensed. The project treats terrain correctly (it doesn't change tick-to-tick), but the mental model is "loaded from LANDFIRE GeoTIFF at scenario init," not "sensed from the environment."

### 3. NWS Gridded Weather Forecasts (NDFD)
The National Weather Service produces gridded forecast products at ~2.5 km resolution, updated hourly. RAWS data is assimilated into the NWS model; what NFDRS/FEMS consumes is the gridded output, not raw sensor streams.

**Maps to:** `FireEnvironmentState`

**Key difference:** Real systems have spatially distributed weather (different conditions at different cells). The project has one global weather state. For a teaching scenario this is acceptable; for a landscape fire simulation it matters.

### 4. Satellite Fire Detection (MODIS / VIIRS)
NASA's MODIS and VIIRS instruments detect active fire hotspots from orbit at 375 m–1 km resolution, with 6–12 hour revisit intervals. The primary operational feed is NASA FIRMS (Fire Information for Resource Management System).

**Maps to:** Closest analog is `ThermalCameraSensor`, but satellite detection has orbital latency and misses fires under heavy smoke.

**Key difference:** Satellite detection is the primary source for fire perimeter and active area in real operations. The project uses ground-level thermal sensors.

### 5. Aerial Infrared (IR) Mapping
Aircraft with FLIR cameras fly fire perimeters, usually at night when smoke clears, and deliver high-resolution perimeter maps as GeoTIFF/KMZ to fire managers.

**Maps to:** `ThermalCameraSensor` is the closest analog, but this is a human-dispatched asset, not a fixed sensor.

### What Is Not Modeled

- **Field observer / spotter reports** — qualitative human observations radioed to dispatch
- **GPS/AVL tracking on resources** — real resources carry GPS that continuously updates position in CAD systems; the project sets resource positions once at scenario init
- **Lightning detection** — relevant for ignition probability modeling

---

## Conscious Tradeoffs — Keep, but Name Them

These simplifications are intentional. The lesson is LangGraph agent coordination, not fire behavior science. Each one is defensible to a professional audience if named explicitly.

### Rothermel ROS Formula — Approximated

**What real Rothermel (1972) computes:**
```
R = (I_R × ξ × (1 + φ_W + φ_S)) / (ρ_b × ε × Q_ig)
```
Where `I_R` is reaction intensity, `ξ` is propagating flux ratio, `φ_W` and `φ_S` are wind and slope multipliers, `ρ_b` is bulk density, `ε` is effective heating number, and `Q_ig` is heat of pre-ignition.

**What the project computes (`_compute_ros()` in `rothermel_physics.py`):**
```
ROS = R₀ × rh_factor × moisture_factor × temp_factor × wind_factor × slope_factor × veg_factor
```
A calibrated factor-product approximation that produces output values in the correct range for the given conditions.

**Why acceptable:** The output units (ft/min), the directional wind logic, the slope multiplier, and the moisture suppression all behave correctly. Fireline intensity and flame length are then computed from ROS using the true Byram (1959) formulas. Professionals will recognize what is being approximated.

**What to say:** *"The ROS calculation is a calibrated approximation of Rothermel (1972). It uses the correct inputs (fuel model, wind, slope, moisture) and produces output in the correct range. The full Rothermel implementation adds reaction intensity and propagating flux ratio terms."*

### Fuel Models — 4 Types Instead of 13 (NFFL) or 40 (Scott-Burgan)

The project uses `GRASSLAND`, `SCRUB`, `FOREST`, `URBAN`. NFFL defines 13 fuel models; Scott-Burgan (the LANDFIRE standard) defines 40.

**Why acceptable:** The base ROS values are within the published ranges for their terrain type analogs. The purpose is to create meaningful variation in fire behavior across the grid, not to produce calibrated predictions for a specific landscape.

**What to say:** *"We use 4 fuel types as a teaching proxy. Production would load LANDFIRE Scott-Burgan 40 fuel model assignments from a GeoTIFF into the same `FuelModel` dataclass."*

### Single Fuel Moisture Value

Real NFDRS tracks four dead fuel timelag classes (1-hour, 10-hour, 100-hour, 1000-hour) and two live fuel classes (herbaceous, woody). Each class responds to weather at a different rate.

**Why acceptable:** A single `fuel_moisture` float still produces the right qualitative behavior — wet cells resist spread, dry cells amplify it. The agent decisions driven by this are directionally correct.

**What to say:** *"Fuel moisture is a single proxy value. NFDRS uses four timelag classes; the 1-hour class is the most fire-behavior-relevant and would be the first to add."*

### Single Global Weather State

`FireEnvironmentState` is one object shared across the entire grid. Real systems have spatially distributed weather.

**Why acceptable:** For a 10×10 teaching scenario, weather variation across the grid is second-order. The important weather dynamics (wind shift, temperature spike, humidity drop) are all present.

**What to say:** *"Weather is uniform across the grid per tick. NFDRS/FEMS ingests NWS gridded forecasts at 2.5 km resolution; the architecture supports distributing weather to per-cell or per-zone states."*

### Sensors as Universal Data Source

All environmental inputs (weather, fire detection) are modeled as `SensorBase` subclasses. In real systems, weather comes from NWS gridded forecasts, fire detection from satellites and aerial IR, and fuel data from LANDFIRE.

**Why acceptable:** The `SensorBase` abstraction is architecturally correct — in production you would subclass it with adapters that pull from RAWS API, FIRMS satellite feed, or NWS NDFD. No agent code would change.

**What to say:** *"Ground sensors are the right abstraction. In production, `SensorBase.read()` is replaced with API adapters for RAWS, FIRMS, or NWS feeds. The cluster agent code and supervisor agent code are unchanged."*

---

## Upgrade Path — Without Touching Agent Code

The architecture has three extension seams that support all meaningful upgrades. None of the following require changes to `graph.py`, `state.py`, or any `tools/` files.

### Seam 1: `FuelModel` Dataclass and `FUEL_MODELS` Dict

**Location:** `src/domains/wildfire/fuel_models.py`

**Upgrades enabled:**
- Expand from 4 to 13 NFFL fuel models or 40 Scott-Burgan models — add entries to `FUEL_MODELS`
- Add `savr_ft2_ft3`, `bulk_density_lb_ft3`, `fuel_depth_ft` fields to `FuelModel` for full Rothermel
- Load from LANDFIRE GeoTIFF: write a loader that reads raster fuel model assignments and populates the grid at init time

**Effort:** Low — additive changes only, no interface modifications

### Seam 2: `PhysicsModule` Interface

**Location:** `src/world/physics.py` (interface), `src/domains/wildfire/rothermel_physics.py` (implementation)

**Upgrades enabled:**
- Implement full Rothermel (1972) formula in `_compute_ros()` using the reaction intensity path
- Add crown fire transition logic (new `FireState` value, transition rules in `tick_physics`)
- Add spotting / ember transport (sample landing cells from a probability distribution based on wind)
- Add per-cell weather by passing a weather grid instead of a single `FireEnvironmentState`
- Plug in an entirely different physics model (e.g., FlamMap's MTT algorithm) without changing anything else

**Effort:** Medium for crown fire and spotting; low for full Rothermel formula

### Seam 3: `SensorBase` Abstraction

**Location:** `src/sensors/base.py`

**Upgrades enabled:**
- Replace `TemperatureSensor.read()` with a RAWS API call (pulls live data from `raws.nifc.gov`)
- Add a `SatelliteObservationSensor` that wraps the NASA FIRMS API with configurable latency (6–12 hour delay to model orbital revisit)
- Add a `NWSWeatherSensor` that pulls gridded NDFD forecast data
- Add an `AerialIRSensor` that models aircraft dispatch, flight time, and perimeter delivery

**Effort:** Low — new subclass per source, no changes to cluster agent or supervisor

---

## Summary for a Demo Audience

> "The fire behavior physics are grounded in the same equations used by operational tools like BehavePlus and FARSITE: Rothermel (1972) Rate of Spread, Byram (1959) fireline intensity and flame length, and the NWCG IRPG fireline intensity thresholds for resource engagement decisions. The resource catalog uses real NWCG identifiers and production rates.
>
> The conscious simplifications are: we use 4 fuel types instead of NFFL's 13 or Scott-Burgan's 40; we use a calibrated approximation of the full Rothermel formula; we model one fuel moisture value instead of four timelag classes; and weather is uniform across the grid. These simplifications live entirely in the physics layer. The agent code — the LangGraph graphs, tools, and resource decision logic — would be unchanged in a production deployment. The physics module, fuel model table, and sensor implementations are the three places you would upgrade."
