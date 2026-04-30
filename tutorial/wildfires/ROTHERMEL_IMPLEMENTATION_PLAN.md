# Rothermel Physics + Resource Sizing — Implementation Plan

## Purpose

Replace the placeholder fire physics with a simplified Rothermel spread model that produces **physical units** (rate of spread, flame length, fireline intensity, acres/hr). Use those outputs to drive a **resource sizing tool** that tells the supervisor LLM what types and quantities of resources are needed — grounded in NWCG operational data.

This plan is **self-contained**. Any model (Opus, Sonnet, or a new session) can pick it up and execute from any step. Each step lists the exact files to create or modify, the interfaces to respect, and the tests to write.

---

## Architecture Context

Read these files before starting any step:

| File | What it tells you |
|------|-------------------|
| `src/world/physics.py` | `PhysicsModule[C]` ABC: `initial_cell_state()`, `tick_physics()`, `summarize()`. `StateEvent[C]` dataclass. |
| `src/world/generic_engine.py` | `GenericWorldEngine`: tick loop, applies `StateEvent`s, records `GenericGroundTruthSnapshot`. |
| `src/domains/wildfire/physics.py` | Current `FirePhysicsModule` — the placeholder being replaced. |
| `src/domains/wildfire/cell_state.py` | `FireCellState`: terrain_type, vegetation, fuel_moisture, slope, fire_state, fire_intensity, fire_start_tick. `ignited()`, `extinguished()` return new instances. |
| `src/domains/wildfire/environment.py` | `FireEnvironmentState`: temperature_c, humidity_pct, wind_speed_mps, wind_direction_deg. `wind_vector()` returns (row_delta, col_delta). |
| `src/domains/wildfire/scenarios.py` | `create_basic_wildfire()`, `create_wildfire_resources()`, `create_full_wildfire_scenario()`. |
| `src/world/grid.py` | `TerrainType` enum: FOREST, GRASSLAND, SCRUB, ROCK, WATER, URBAN. `FireState` enum: UNBURNED, BURNING, BURNED. |
| `src/resources/base.py` | `ResourceBase` Pydantic model: resource_id, resource_type, cluster_id, status, capacity, available, mobile, metadata. |
| `src/resources/inventory.py` | `ResourceInventory`: register, by_cluster, by_type, readiness_summary, scenario knobs. |
| `src/tools/resource_tools.py` | 4 @tool functions: get_resource_summary, get_resources_by_cluster, get_resources_by_type, check_preparedness. Uses `_get_inventory()` from shared `_SupervisorToolState`. |
| `src/tools/supervisor_tools.py` | `_SupervisorToolState`, `set_supervisor_tool_state()`, `clear_supervisor_tool_state()`. SUPERVISOR_TOOLS list. |
| `src/agents/supervisor/graph.py` | `build_supervisor_graph()` — combines SUPERVISOR_TOOLS + RESOURCE_TOOLS when resource_inventory is provided. |
| `docs/tutorial/wildfires/wirldfire-logic.md` | Rothermel reference: formulas for ROS, flame length, fireline intensity, acres/hr. Danger rating tiers. |
| `docs/tutorial/wildfires/resources.py` | NWCG resource catalog: crews (production_rate_chains_hr), engines (tank_gal, pump_gpm), dozers, aircraft (capacity_gal), cache items. |

---

## Constraints

1. **PhysicsModule interface is sacred.** `RothermelFirePhysicsModule` must implement `initial_cell_state()`, `tick_physics()`, `summarize()` — same as the current placeholder.
2. **FireCellState is unchanged.** The new physics module reads the same cell fields. If new fields are needed, they are added as optional with defaults so existing code doesn't break.
3. **GenericWorldEngine is unchanged.** It calls `tick_physics()` and applies `StateEvent`s. The engine doesn't know about Rothermel.
4. **Existing scenarios still work.** `create_basic_wildfire()` can use either physics module. A parameter selects which one.
5. **No new dependencies.** The Rothermel model uses only `math` and `random` from the standard library.
6. **Tests run with `PYTHONPATH=src pytest`.**
7. **Existing tests must not break.** Rename the old physics module to `SimpleFirePhysicsModule`; keep it importable from the same path.

---

## Steps

### Step 1: Add fire behavior metrics to FireCellState

**File:** `src/domains/wildfire/cell_state.py`

Add optional fields to `FireCellState` for Rothermel-derived metrics. These are computed by the physics module and stored per-cell so that tools and summaries can read them.

```python
# New optional fields (add after fire_start_tick)
rate_of_spread_ft_min: float = 0.0       # Rothermel ROS at this cell
flame_length_ft: float = 0.0             # Byram flame length
fireline_intensity_btu_ft_s: float = 0.0  # Byram fireline intensity
```

**Why per-cell?** Because ROS depends on the cell's fuel type, moisture, and slope — it varies across the grid. The supervisor tool needs to query "what's the fireline intensity in cluster-south?" which requires per-cell values.

Update `ignited()` to accept optional metrics and carry them forward. Update `extinguished()` to zero them out.

**Tests:** `tests/domains/wildfire/test_cell_state.py` — add tests for new fields, ensure defaults are 0.0, ensure `ignited()` carries them, ensure `extinguished()` zeros them.

---

### Step 2: Add fuel model data

**File:** `src/domains/wildfire/fuel_models.py` (NEW)

Create a lookup table mapping `TerrainType` to Rothermel fuel parameters. Based on the reference doc (`docs/tutorial/wildfires/wirldfire-logic.md`).

```python
@dataclass(frozen=True)
class FuelModel:
    """Rothermel fuel parameters for a terrain type."""
    base_spread_rate_ft_min: float  # R₀ — base ROS at reference conditions
    heat_content_btu_lb: float      # Heat content for fireline intensity calc
    moisture_of_extinction: float   # Fuel moisture % above which fire won't sustain
    description: str

FUEL_MODELS: Dict[TerrainType, FuelModel] = {
    TerrainType.GRASSLAND: FuelModel(
        base_spread_rate_ft_min=18.0,
        heat_content_btu_lb=8000,
        moisture_of_extinction=0.15,
        description="Dry grass / shrubland — fast spread, lower intensity",
    ),
    TerrainType.SCRUB: FuelModel(
        base_spread_rate_ft_min=12.0,
        heat_content_btu_lb=9500,
        moisture_of_extinction=0.20,
        description="Chaparral / dense shrub — moderate spread, high intensity",
    ),
    TerrainType.FOREST: FuelModel(
        base_spread_rate_ft_min=6.0,
        heat_content_btu_lb=8500,
        moisture_of_extinction=0.25,
        description="Timber litter — slower spread, sustained burn",
    ),
    TerrainType.URBAN: FuelModel(
        base_spread_rate_ft_min=8.0,
        heat_content_btu_lb=9000,
        moisture_of_extinction=0.10,
        description="Urban fuel loads — variable spread, high structure risk",
    ),
    # ROCK and WATER have no fuel model — they are non-burnable.
}
```

**Tests:** `tests/domains/wildfire/test_fuel_models.py` — verify all burnable terrain types have entries, ROCK and WATER do not.

---

### Step 3: Add NWCG resource catalog

**File:** `src/domains/wildfire/nwcg_resources.py` (NEW)

Formalize the data from `docs/tutorial/wildfires/resources.py` into typed dataclasses. This is the lookup table for resource sizing.

```python
@dataclass(frozen=True)
class NWCGResourceSpec:
    """NWCG standard resource specification."""
    nwcg_id: str               # e.g. "C-1", "E-3", "H-1"
    kind: str                  # e.g. "Crew", "Engine", "Helicopter"
    nwcg_type: int             # NWCG type number (1=heavy, higher=lighter)
    name: str                  # Full name
    category: str              # "Personnel", "Equipment", "Aircraft"
    # Operational capability (not all apply to all types)
    production_rate_chains_hr: Optional[float] = None  # Fireline construction rate
    tank_gal: Optional[float] = None                    # Water capacity
    pump_gpm: Optional[float] = None                    # Pump rate
    capacity_gal: Optional[float] = None                # Aircraft drop capacity

NWCG_CATALOG: List[NWCGResourceSpec] = [...]  # From docs/tutorial/wildfires/resources.py

# Fireline intensity thresholds for resource typing
# Source: Rothermel/Byram operational guidelines
INTENSITY_THRESHOLDS = {
    "hand_crew":    100,    # BTU/ft/s — hand crews effective below this
    "engine":       500,    # BTU/ft/s — engines effective below this
    "dozer":       1000,    # BTU/ft/s — dozers effective below this
    "air_tanker":  2000,    # BTU/ft/s — aerial marginal above this
}
```

**Tests:** `tests/domains/wildfire/test_nwcg_resources.py` — verify catalog entries, intensity thresholds are ordered.

---

### Step 4: Implement RothermelFirePhysicsModule

**File:** `src/domains/wildfire/rothermel_physics.py` (NEW)

This is the core implementation. It replaces the placeholder's dice-roll spread with Rothermel-computed ROS that is then converted to a spread probability for the cellular automaton.

**Key design:** The Rothermel model computes a per-cell ROS in ft/min. To integrate with the grid-based cellular automaton, we convert ROS to a spread probability per tick:

```
cell_size_ft = grid dimension / number of cells (configurable, default ~200 ft)
time_step_min = minutes per tick (configurable, default ~5 min)

spread_distance_ft = ROS × time_step_min
prob_spread = min(0.95, spread_distance_ft / cell_size_ft)
```

This means: if ROS says fire travels 90 ft/min and a tick is 5 minutes, fire can travel 450 ft. If a cell is 200 ft across, that's a probability well above 1.0 → clamped to 0.95. This naturally produces faster spread for high-ROS conditions.

```python
class RothermelFirePhysicsModule(PhysicsModule[FireCellState]):
    """
    Simplified Rothermel fire spread model.

    Implements PhysicsModule[FireCellState] — drop-in replacement for
    SimpleFirePhysicsModule.

    Computes Rate of Spread (ROS) from fuel model, weather, and terrain,
    then converts to per-tick spread probability for the cellular automaton.
    Also computes derived metrics (flame length, fireline intensity) and
    stores them on FireCellState for tool access.

    Based on:
      - Rothermel (1972) — rate of spread
      - Byram (1959) — fireline intensity and flame length
      - Anderson (1983) — elliptical fire shape

    See docs/tutorial/wildfires/wirldfire-logic.md for formulas.
    """

    def __init__(
        self,
        *,
        cell_size_ft: float = 200.0,
        time_step_min: float = 5.0,
        burn_duration_ticks: int = 5,
    ) -> None: ...

    def initial_cell_state(self, row, col, layer=0) -> FireCellState: ...

    def tick_physics(self, grid, environment, tick) -> List[StateEvent[FireCellState]]:
        """
        For each burning cell:
          1. Compute ROS from Rothermel: R₀ × φ_wind × φ_slope × moisture × humidity
          2. Compute flame_length, fireline_intensity from Byram
          3. Convert ROS to spread probability: (ROS × time_step) / cell_size
          4. For each unburned burnable neighbor, roll against probability
          5. If spread: create StateEvent with ignited state + metrics
          6. If burn duration exceeded: create StateEvent with extinguished state
        """
        ...

    def summarize(self, grid) -> Dict[str, Any]:
        """
        Returns everything the old summarize() did PLUS:
          - avg_ros_ft_min: mean ROS across burning cells
          - max_ros_ft_min: peak ROS
          - avg_flame_length_ft: mean flame length
          - max_fireline_intensity: peak intensity
          - estimated_acres_hr: from Anderson elliptical model
          - danger_rating: Low/Moderate/High/Very High/Extreme
        """
        ...

    # ── Internal computation methods ──────────────────────────

    def _compute_ros(self, fuel_model, environment, cell_state,
                     wind_alignment) -> float:
        """
        ROS = R₀ × rh_factor × moisture_factor × temp_factor × wind_factor × slope_factor

        Uses formulas from docs/tutorial/wildfires/wirldfire-logic.md.
        Returns ft/min.
        """
        ...

    def _compute_flame_length(self, ros, heat_content) -> float:
        """Byram: L = (ROS × heat_content / 500) ^ 0.46. Returns ft."""
        ...

    def _compute_fireline_intensity(self, ros, heat_content,
                                     moisture_factor) -> float:
        """I = ROS × heat_content × moisture_factor × 0.9. Returns BTU/ft/s."""
        ...

    def _compute_acres_per_hour(self, ros, wind_speed) -> float:
        """Anderson elliptical model. Returns acres/hr."""
        ...

    def _ros_to_spread_probability(self, ros) -> float:
        """Convert ROS (ft/min) to per-tick probability given cell_size and time_step."""
        spread_distance = ros * self._time_step_min
        return min(0.95, spread_distance / self._cell_size_ft)

    def _danger_rating(self, ros) -> str:
        """Map ROS to danger tier. Max ROS = 40 ft/min."""
        pct = ros / 40.0
        if pct < 0.20: return "Low"
        if pct < 0.40: return "Moderate"
        if pct < 0.60: return "High"
        if pct < 0.80: return "Very High"
        return "Extreme"
```

**Tests:** `tests/domains/wildfire/test_rothermel_physics.py`:
- `test_ros_grassland_hot_dry_windy` — high ROS (near 18 ft/min base × modifiers)
- `test_ros_forest_wet_calm` — low ROS (6 ft/min base × suppressors)
- `test_flame_length_formula` — known inputs → expected output
- `test_fireline_intensity_formula` — known inputs → expected output
- `test_spread_probability_conversion` — ROS → probability mapping
- `test_danger_rating_tiers` — each tier boundary
- `test_fire_spreads_on_grid` — run 20 ticks on basic scenario, verify fire spreads
- `test_metrics_populated_on_burning_cells` — after tick, burning cells have non-zero ROS/flame/intensity
- `test_extinguished_cells_zero_metrics` — burned-out cells have 0.0 metrics
- `test_summarize_includes_fire_behavior` — summarize() returns avg_ros, danger_rating, etc.

---

### Step 5: Rename existing physics module

**File:** `src/domains/wildfire/physics.py`

Rename `FirePhysicsModule` → `SimpleFirePhysicsModule`. Add an alias so existing imports don't break:

```python
class SimpleFirePhysicsModule(PhysicsModule[FireCellState]):
    # ... (existing code, unchanged)

# Backward compatibility alias
FirePhysicsModule = SimpleFirePhysicsModule
```

Update the module docstring to say "Simple probabilistic fire spread — see rothermel_physics.py for the Rothermel-based model."

**Tests:** Run all existing tests — they should pass unchanged because of the alias.

---

### Step 6: Update scenarios to support both physics modules

**File:** `src/domains/wildfire/scenarios.py`

Update `create_basic_wildfire()` to accept an optional `physics_model` parameter:

```python
def create_basic_wildfire(
    *,
    use_rothermel: bool = True,
    cell_size_ft: float = 200.0,
    time_step_min: float = 5.0,
) -> GenericWorldEngine[FireCellState]:
    if use_rothermel:
        from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule
        physics = RothermelFirePhysicsModule(
            cell_size_ft=cell_size_ft,
            time_step_min=time_step_min,
            burn_duration_ticks=5,
        )
    else:
        physics = SimpleFirePhysicsModule(
            base_probability=0.15,
            burn_duration_ticks=5,
        )
    # ... rest of scenario unchanged
```

Update `create_full_wildfire_scenario()` similarly.

Update `__init__.py` to export `RothermelFirePhysicsModule` and `SimpleFirePhysicsModule`.

**Tests:** `tests/domains/wildfire/test_scenarios.py` — add test for `use_rothermel=True` and `use_rothermel=False`.

---

### Step 7: Add fire behavior tool for supervisor

**File:** `src/tools/fire_behavior_tools.py` (NEW)

New LangGraph tools the supervisor calls to get fire behavior metrics and resource sizing recommendations. These read from the physics module's `summarize()` output stored in ground truth, or from a live computation.

```python
@tool
def get_fire_behavior() -> Dict[str, Any]:
    """Get current fire behavior metrics from the simulation.

    Returns ROS (ft/min), flame length (ft), fireline intensity (BTU/ft/s),
    estimated acres/hr, and danger rating.
    """
    ...

@tool
def get_resource_needs(cluster_id: Optional[str] = None) -> Dict[str, Any]:
    """Estimate resource needs based on current fire behavior.

    Uses fireline intensity to determine which resource types can effectively
    engage, and ROS to estimate how many units are needed to match
    fire perimeter growth.

    Returns:
      - suppression_difficulty: hand_crew / engine / dozer / aerial_only / beyond_suppression
      - recommended_resources: list of {nwcg_id, name, quantity, reason}
      - perimeter_growth_chains_hr: estimated fire perimeter growth rate
      - production_needed_chains_hr: fireline production needed to contain
    """
    ...

@tool
def compare_resources_to_needs(cluster_id: Optional[str] = None) -> Dict[str, Any]:
    """Compare available resources against estimated needs.

    Combines fire behavior assessment with resource inventory to produce
    a gap analysis: what we have vs. what we need.

    Returns:
      - adequate: bool — are current resources sufficient?
      - available: dict of resource types and counts on hand
      - needed: dict of resource types and counts required
      - gaps: list of shortfalls
      - surplus: list of excess resources
    """
    ...

FIRE_BEHAVIOR_TOOLS = [get_fire_behavior, get_resource_needs, compare_resources_to_needs]
```

**State management:** These tools need access to:
1. Fire behavior metrics (from physics summarize output or live grid)
2. NWCG catalog (from `nwcg_resources.py`)
3. ResourceInventory (from existing `_SupervisorToolState`)

Add `fire_behavior_summary: Optional[Dict]` to `_SupervisorToolState` in `supervisor_tools.py`. The supervisor graph sets this from the latest `domain_summary` before the LLM loop.

**Tests:** `tests/tools/test_fire_behavior_tools.py`:
- `test_get_fire_behavior_returns_metrics`
- `test_resource_needs_low_intensity` — recommends hand crews
- `test_resource_needs_high_intensity` — recommends dozers + aerial
- `test_compare_adequate` — resources match needs → adequate=True
- `test_compare_gap` — resources insufficient → lists gaps

---

### Step 8: Wire fire behavior tools into supervisor graph

**File:** `src/agents/supervisor/graph.py`

Update `build_supervisor_graph()` to include `FIRE_BEHAVIOR_TOOLS` alongside `SUPERVISOR_TOOLS` and `RESOURCE_TOOLS`:

```python
from tools.fire_behavior_tools import FIRE_BEHAVIOR_TOOLS

# In the tool composition section:
all_tools = SUPERVISOR_TOOLS
if resource_inventory is not None:
    all_tools = all_tools + RESOURCE_TOOLS
if fire_behavior_summary is not None:
    all_tools = all_tools + FIRE_BEHAVIOR_TOOLS
```

Add `fire_behavior_summary: Optional[Dict] = None` parameter to `build_supervisor_graph()`.

Update `set_supervisor_tool_state()` to accept and store `fire_behavior_summary`.

**Tests:** Existing supervisor tests should still pass (fire behavior tools are optional). Add a test in `tests/agents/test_supervisor.py` verifying that fire behavior tools appear when `fire_behavior_summary` is provided.

---

### Step 9: Enrich ResourceBase metadata for NWCG alignment

**File:** `src/domains/wildfire/scenarios.py`

Update `create_wildfire_resources()` to use NWCG-aligned resource types with operational fields in metadata:

```python
# Before:
ResourceBase(
    resource_id="firetruck-1",
    resource_type="firetruck",
    capacity=500.0,
    metadata={"unit": "gallons", "crew_size": 4, "model": "Type 1"},
)

# After:
ResourceBase(
    resource_id="engine-south-1",
    resource_type="engine",
    capacity=500.0,
    metadata={
        "nwcg_id": "E-3",
        "nwcg_type": 3,
        "name": "Wildland Engine (4x4)",
        "unit": "gallons",
        "tank_gal": 500,
        "pump_gpm": 150,
        "category": "Equipment",
    },
)
```

Also add crew resources (the current scenario only has equipment and medical):

```python
ResourceBase(
    resource_id="crew-south-1",
    resource_type="crew",
    cluster_id="cluster-south",
    grid_row=9, grid_col=4,
    capacity=1.0,   # 1 crew unit
    available=1.0,
    mobile=True,
    metadata={
        "nwcg_id": "C-1",
        "nwcg_type": 1,
        "name": "Interagency Hotshot Crew",
        "unit": "20-person",
        "production_rate_chains_hr": 15,
        "category": "Personnel",
    },
)
```

**Tests:** Update `tests/resources/` and `tests/domains/wildfire/test_scenarios.py` to verify NWCG metadata is present.

---

### Step 10: Update ground truth to include fire behavior summary

**File:** `src/world/generic_engine.py`

No changes needed — `domain_summary` already captures whatever `physics.summarize()` returns. The Rothermel module's `summarize()` naturally includes fire behavior metrics.

Verify that `GenericGroundTruthSnapshot.domain_summary` now contains `avg_ros_ft_min`, `danger_rating`, etc. after running with the Rothermel module.

**Tests:** `tests/world/test_generic_engine.py` (or add to existing) — tick with Rothermel, verify snapshot.domain_summary has fire behavior fields.

---

### Step 11: Update check_preparedness to be fire-behavior-aware

**File:** `src/tools/resource_tools.py`

Update `check_preparedness()` to include fire behavior context in its gap analysis when `fire_behavior_summary` is available:

```python
# In check_preparedness(), after existing gap checks:
fire_behavior = _get_fire_behavior()  # from _SupervisorToolState
if fire_behavior:
    intensity = fire_behavior.get("max_fireline_intensity", 0)
    if intensity > 100 and "crew" not in types_present:
        gaps.append(f"Fireline intensity {intensity:.0f} BTU/ft/s exceeds hand-crew threshold but no crews assigned")
    if intensity > 500 and "dozer" not in types_present:
        gaps.append(f"Fireline intensity {intensity:.0f} BTU/ft/s — dozers recommended but none assigned")
    if intensity > 1000 and "helicopter" not in types_present and "air_tanker" not in types_present:
        gaps.append(f"Fireline intensity {intensity:.0f} BTU/ft/s — aerial resources needed but none assigned")
```

**Tests:** `tests/resources/test_resource_tools.py` — add tests for fire-behavior-aware gap analysis.

---

### Step 12: Write integration tests

**File:** `tests/integration/test_rothermel_pipeline.py` (NEW)

End-to-end test: create scenario with Rothermel physics → run 20 ticks → verify:
1. Fire spreads (burning cells > 0)
2. Ground truth has fire behavior metrics (ROS, flame length, intensity)
3. `get_fire_behavior()` tool returns valid metrics
4. `get_resource_needs()` recommends appropriate resource types for the intensity level
5. `compare_resources_to_needs()` identifies gaps when resources are degraded
6. Supervisor graph (stub mode) produces commands that reference resource types

---

## Execution Order

Steps 1–3 are independent (can be done in parallel or any order).
Steps 4 depends on 1 + 2.
Step 5 is independent (just a rename).
Step 6 depends on 4 + 5.
Step 7 depends on 3 + 4.
Step 8 depends on 7.
Step 9 depends on 3.
Step 10 depends on 4.
Step 11 depends on 7.
Step 12 depends on all previous steps.

**Suggested linear order:** 1 → 2 → 3 → 5 → 4 → 6 → 7 → 9 → 8 → 10 → 11 → 12

## Verification Commands

```bash
# Run all existing tests (should still pass after each step)
PYTHONPATH=src pytest tests/ -v

# Run only the new Rothermel tests
PYTHONPATH=src pytest tests/domains/wildfire/test_rothermel_physics.py -v

# Run only the fire behavior tool tests
PYTHONPATH=src pytest tests/tools/test_fire_behavior_tools.py -v

# Run the integration test
PYTHONPATH=src pytest tests/integration/test_rothermel_pipeline.py -v

# Quick smoke test — run 20 ticks and print fire behavior
PYTHONPATH=src python -c "
from domains.wildfire import create_basic_wildfire
engine = create_basic_wildfire(use_rothermel=True)
for _ in range(20):
    s = engine.tick()
    fb = s.domain_summary
    print(f'Tick {s.tick}: burning={s.grid_summary.get(\"BURNING\",0)} '
          f'ROS={fb.get(\"avg_ros_ft_min\",0):.1f} ft/min '
          f'intensity={fb.get(\"max_fireline_intensity\",0):.0f} BTU/ft/s '
          f'danger={fb.get(\"danger_rating\",\"N/A\")}')
"
```

## Files Created/Modified Summary

| Action | File | Step |
|--------|------|------|
| MODIFY | `src/domains/wildfire/cell_state.py` | 1 |
| CREATE | `src/domains/wildfire/fuel_models.py` | 2 |
| CREATE | `src/domains/wildfire/nwcg_resources.py` | 3 |
| CREATE | `src/domains/wildfire/rothermel_physics.py` | 4 |
| MODIFY | `src/domains/wildfire/physics.py` | 5 |
| MODIFY | `src/domains/wildfire/scenarios.py` | 6 |
| MODIFY | `src/domains/wildfire/__init__.py` | 6 |
| CREATE | `src/tools/fire_behavior_tools.py` | 7 |
| MODIFY | `src/tools/supervisor_tools.py` | 7, 8 |
| MODIFY | `src/agents/supervisor/graph.py` | 8 |
| MODIFY | `src/tools/resource_tools.py` | 11 |
| CREATE | `tests/domains/wildfire/test_fuel_models.py` | 2 |
| CREATE | `tests/domains/wildfire/test_nwcg_resources.py` | 3 |
| CREATE | `tests/domains/wildfire/test_rothermel_physics.py` | 4 |
| CREATE | `tests/tools/test_fire_behavior_tools.py` | 7 |
| CREATE | `tests/integration/test_rothermel_pipeline.py` | 12 |

## What This Achieves

After all steps, the supervisor LLM has access to:

1. **Fire behavior metrics** — "ROS is 24 ft/min, flame length is 15 ft, intensity is 850 BTU/ft/s, danger rating is Very High"
2. **Resource needs** — "At this intensity, dozers and engines are effective. Estimated perimeter growth is 40 chains/hr. Need 3 hotshot crews or 1 heavy dozer to keep pace."
3. **Gap analysis** — "Cluster-south has 1 engine and 0 dozers. At current intensity, engines are marginal and dozers are needed. Gap: 1 heavy dozer or 2 hotshot crews."

This is grounded in Rothermel + Byram + NWCG operational data. No hand-waving. A reviewer can trace every number back to a cited formula or published standard.
