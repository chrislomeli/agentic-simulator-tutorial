"""
ogar.domains.wildfire.scenarios

Pre-built wildfire scenarios using the generic engine + fire domain.

Each scenario function returns a fully configured GenericWorldEngine
ready to tick.

basic_wildfire
──────────────
A 10×10 grid with mixed terrain:
  - Forest in the north (high fuel, moderate moisture)
  - Grassland in the south (medium fuel, low moisture)
  - Rock ridge through the middle (firebreak with a gap)
  - Urban area in the south-east (buildings to protect)
  - Lake in the north-west (impassable)

Weather: hot, dry, south-west wind.
Ignition: cell (7, 2) in the south-west grassland.

The gap in the rock ridge at (4,6)-(4,7) is the decision point —
will the fire jump the ridge?  The agent has to monitor both sides.
"""

from __future__ import annotations

from typing import Tuple

from domains.wildfire.cell_state import FireCellState, FireState, TerrainType
from domains.wildfire.environment import FireEnvironmentState
from domains.wildfire.physics import SimpleFirePhysicsModule
from resources.base import ResourceBase, ResourceStatus
from resources.inventory import ResourceInventory
from world.generic_engine import GenericWorldEngine
from world.generic_grid import GenericTerrainGrid


def create_basic_wildfire(
    *,
    use_rothermel: bool = True,
    cell_size_ft: float = 200.0,
    time_step_min: float = 5.0,
) -> GenericWorldEngine[FireCellState]:
    """
    Create a fully configured wildfire scenario.

    Returns a GenericWorldEngine ready to tick.

    Parameters
    ──────────
    use_rothermel : When True (default), use RothermelFirePhysicsModule for
                    physics-grounded fire spread.  When False, use the simple
                    probabilistic SimpleFirePhysicsModule.
    cell_size_ft  : Grid cell spatial extent in feet (Rothermel only).
    time_step_min : Minutes per simulation tick (Rothermel only).

    Grid layout (10×10):
      Row 0-1 col 0: WATER (lake)
      Row 0-3: FOREST (high vegetation)
      Row 4: ROCK ridge (gap at cols 6-7 with SCRUB)
      Row 5-9: GRASSLAND (dry)
      Row 7-8, col 8-9: URBAN
      Fire starts at (7, 2) — south-west grassland.
      Wind from SW (225°) → pushes fire north-east.
    """
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

    # ── Build grid with custom initial states ─────────────────────
    # We use the default factory first, then overwrite cells.
    grid = GenericTerrainGrid(
        rows=10, cols=10,
        initial_state_factory=physics.initial_cell_state,
    )

    # ── North: lake (north-west corner) ───────────────────────────
    for r in range(2):
        grid.update_cell_state(r, 0, FireCellState(
            terrain_type=TerrainType.WATER,
            vegetation=0.0,
        ))

    # ── North: forest (rows 0–3) ─────────────────────────────────
    for r in range(4):
        for c in range(10):
            current = grid.get_cell(r, c).cell_state
            if current.terrain_type == TerrainType.WATER:
                continue
            grid.update_cell_state(r, c, FireCellState(
                terrain_type=TerrainType.FOREST,
                vegetation=0.85,
                fuel_moisture=0.3,
                slope=5.0,  # slight uphill in the north
            ))

    # ── Middle: rock ridge (row 4) ────────────────────────────────
    for c in range(10):
        if c in (6, 7):
            # Gap in the ridge — scrub, fire might jump through.
            grid.update_cell_state(4, c, FireCellState(
                terrain_type=TerrainType.SCRUB,
                vegetation=0.4,
                fuel_moisture=0.2,
            ))
        else:
            grid.update_cell_state(4, c, FireCellState(
                terrain_type=TerrainType.ROCK,
                vegetation=0.0,
            ))

    # ── South: grassland (rows 5–9) ──────────────────────────────
    for r in range(5, 10):
        for c in range(10):
            grid.update_cell_state(r, c, FireCellState(
                terrain_type=TerrainType.GRASSLAND,
                vegetation=0.6,
                fuel_moisture=0.15,
            ))

    # ── South-east: urban area ────────────────────────────────────
    for r in (7, 8):
        for c in (8, 9):
            grid.update_cell_state(r, c, FireCellState(
                terrain_type=TerrainType.URBAN,
                vegetation=0.1,
                fuel_moisture=0.05,
            ))

    # ── Weather: hot, dry, south-west wind ────────────────────────
    environment = FireEnvironmentState(
        temperature_c=38.0,
        humidity_pct=12.0,
        wind_speed_mps=8.0,
        wind_direction_deg=225.0,
        pressure_hpa=1008.0,
    )

    # ── Build engine ──────────────────────────────────────────────
    engine = GenericWorldEngine(
        grid=grid,
        environment=environment,
        physics=physics,
    )

    # ── Initial ignition ──────────────────────────────────────────
    """
      get_cell(7,2).cell_state retrieves the current FireCellState for that cell. Then .ignited(tick=0, intensity=0.8) doesn't modify it — it returns a new FireCellState with fire_state=BURNING. The original cell is untouched.                                                                                                                                                                                                                                                                                                                                                                                                                     
      inject_state takes that new state object and puts it into the grid at (7,2), replacing the old one.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              
      Why not just cell.ignite() directly? Because FireCellState is a Pydantic model and we chose to make it immutable — state changes return new instances via model_copy(update=...). This is what enables the StateEvent pattern: the physics module produces new state objects and the engine applies them atomically, rather than physics code reaching in and mutating cells directly.                                                                                                                                                                                                                                                                     
      The reason we read the cell first is that ignited() is a method on FireCellState, not a constructor — it carries forward all the existing cell's properties (terrain, vegetation, moisture, slope) and only changes the fire-related fields. If you constructed a fresh FireCellState(fire_state=BURNING) you'd lose all the terrain setup.                                                                                                                                                                                                                                                                                                                
      So the read is load-existing-state, .ignited() is create-modified-copy, inject_state is write-back.    
    """
    ignition_state = grid.get_cell(7, 2).cell_state.ignited(tick=0, intensity=0.8)
    engine.inject_state(7, 2, ignition_state)

    return engine


def create_wildfire_resources(grid_rows: int = 10, grid_cols: int = 10) -> ResourceInventory:
    """
    Create a ResourceInventory with NWCG-aligned preparedness assets for the
    basic wildfire scenario.

    Resource layout (matching the 10×10 basic wildfire grid):

      Crew:
        crew-south-1 : cluster-south, at (9, 1) — IHC hotshot crew
        crew-south-2 : cluster-south, at (9, 3) — Type-2 hand crew

      Engines:
        engine-south-1 : cluster-south, at (9, 0) — Wildland Engine (E-3)
        engine-south-2 : cluster-south, at (9, 9) — Wildland Engine (E-3)

      Dozer:
        dozer-south-1 : cluster-south, at (9, 5) — Heavy Dozer (D-1)

      Medical:
        ambulance-1 : cluster-south, at (8, 5) — ambulance
        hospital-1  : cluster-south, at (7, 9) — 50-bed hospital

      Aircraft:
        heli-1      : cluster-north, at (0, 5) — Heavy Helicopter (H-1)

    This mirrors a realistic deployment: fire assets near the ignition
    zone (south), medical assets near the urban area (south-east),
    aerial assets at a remote airfield (north).
    """
    inventory = ResourceInventory(grid_rows=grid_rows, grid_cols=grid_cols)

    # ── Hotshot crew (IHC, C-1) ───────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="crew-south-1",
        resource_type="crew",
        cluster_id="cluster-south",
        grid_row=9, grid_col=1,
        capacity=1.0,   # 1 crew unit (20-person)
        available=1.0,
        mobile=True,
        metadata={
            "nwcg_id": "C-1",
            "nwcg_type": 1,
            "name": "Interagency Hotshot Crew (IHC)",
            "unit": "20-person",
            "production_rate_chains_hr": 15,
            "category": "Personnel",
        },
    ))

    # ── Hand crew (C-2) ───────────────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="crew-south-2",
        resource_type="crew",
        cluster_id="cluster-south",
        grid_row=9, grid_col=3,
        capacity=1.0,
        available=1.0,
        mobile=True,
        metadata={
            "nwcg_id": "C-2",
            "nwcg_type": 2,
            "name": "Hand Crew",
            "unit": "20-person",
            "production_rate_chains_hr": 8,
            "category": "Personnel",
        },
    ))

    # ── Wildland Engine SW (E-3) ──────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="engine-south-1",
        resource_type="engine",
        cluster_id="cluster-south",
        grid_row=9, grid_col=0,
        capacity=500.0,
        available=500.0,
        mobile=True,
        metadata={
            "nwcg_id": "E-3",
            "nwcg_type": 3,
            "name": "Wildland Engine (4x4)",
            "unit": "gallons",
            "tank_gal": 500,
            "pump_gpm": 150,
            "category": "Equipment",
        },
    ))

    # ── Wildland Engine SE (E-3) ──────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="engine-south-2",
        resource_type="engine",
        cluster_id="cluster-south",
        grid_row=9, grid_col=9,
        capacity=500.0,
        available=500.0,
        mobile=True,
        metadata={
            "nwcg_id": "E-3",
            "nwcg_type": 3,
            "name": "Wildland Engine (4x4)",
            "unit": "gallons",
            "tank_gal": 500,
            "pump_gpm": 150,
            "category": "Equipment",
        },
    ))

    # ── Heavy Dozer (D-1) ─────────────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="dozer-south-1",
        resource_type="dozer",
        cluster_id="cluster-south",
        grid_row=9, grid_col=5,
        capacity=1.0,   # 1 dozer unit
        available=1.0,
        mobile=True,
        metadata={
            "nwcg_id": "D-1",
            "nwcg_type": 1,
            "name": "Heavy Dozer (D8/D7)",
            "unit": "Vehicle",
            "production_rate_chains_hr": 60,
            "category": "Equipment",
        },
    ))

    # ── Ambulance ─────────────────────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="ambulance-1",
        resource_type="ambulance",
        cluster_id="cluster-south",
        grid_row=8, grid_col=5,
        capacity=2.0,
        available=2.0,
        mobile=True,
        metadata={"unit": "patients", "crew_size": 2, "category": "Medical"},
    ))

    # ── Hospital ──────────────────────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="hospital-1",
        resource_type="hospital",
        cluster_id="cluster-south",
        grid_row=7, grid_col=9,
        capacity=50.0,
        available=42.0,
        mobile=False,
        metadata={"unit": "beds", "trauma_center": True, "category": "Medical"},
    ))

    # ── Heavy Helicopter (H-1) ────────────────────────────────────
    inventory.register(ResourceBase(
        resource_id="heli-1",
        resource_type="helicopter",
        cluster_id="cluster-north",
        grid_row=0, grid_col=5,
        capacity=700.0,
        available=700.0,
        mobile=True,
        metadata={
            "nwcg_id": "H-1",
            "nwcg_type": 1,
            "name": "Heavy Helicopter (Type 1)",
            "unit": "gallons",
            "capacity_gal": 700,
            "category": "Aircraft",
        },
    ))

    return inventory


def create_full_wildfire_scenario(
    *,
    use_rothermel: bool = True,
    cell_size_ft: float = 200.0,
    time_step_min: float = 5.0,
) -> Tuple[GenericWorldEngine[FireCellState], ResourceInventory]:
    """
    Convenience function that returns both the engine and resource inventory.

    Use this when you want the complete scenario with preparedness assets.

    Parameters
    ──────────
    use_rothermel : When True (default), use RothermelFirePhysicsModule.
    cell_size_ft  : Grid cell spatial extent in feet (Rothermel only).
    time_step_min : Minutes per simulation tick (Rothermel only).

    Returns:
        (engine, resource_inventory) tuple.
    """
    engine = create_basic_wildfire(
        use_rothermel=use_rothermel,
        cell_size_ft=cell_size_ft,
        time_step_min=time_step_min,
    )
    resources = create_wildfire_resources(
        grid_rows=engine.grid.rows,
        grid_cols=engine.grid.cols,
    )
    return engine, resources
