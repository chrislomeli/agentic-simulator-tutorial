"""
world-simulator.agents.logistics.tools.spread

Tool: simulate_spread_from
──────────────────────────
Lets the logistics LLM ask: "if cell (r, c) ignited right now, where
would the fire be in N ticks?"

This tool is fundamentally different from the other two in this package:

  - get_resources_within   — a READ over inventory state.
  - get_wind_history       — a READ over historical metric state.
  - simulate_spread_from   — a COMPUTATION on a hypothetical world.

The LLM cannot reliably do Rothermel physics in its head. The simulator
already implements it. This tool exposes the physics module to the LLM
as a "what-if" query — without mutating the live world.

The hardest design constraint
─────────────────────────────
The hypothetical run must NOT touch the live grid. Two strategies:

  A. Have the physics module expose a hypothetical-run classmethod that
     operates on a copy internally. Cleanest long-term API.

  B. Deepcopy the world grid at the tool boundary, run existing
     ``tick_physics`` on the copy. Simpler to implement; safe as long
     as nobody mutates global registries during the run.

This stub is structured for option B (cheaper to land first). Switching
to option A later is a local refactor inside this file — the input and
output schemas don't change.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field

from domains.wildfire.rothermel_physics import RothermelFirePhysicsModule
from world.generic_grid import GenericTerrainGrid

# ═══════════════════════════════════════════════════════════════════════════════
# Input schema
# ═══════════════════════════════════════════════════════════════════════════════


class SimulateSpreadFromInput(BaseModel):
    """Arguments Claude provides when calling simulate_spread_from."""

    cell_row: int = Field(
        description="Row of the hypothetical ignition cell.",
        ge=0,
    )
    cell_col: int = Field(
        description="Column of the hypothetical ignition cell.",
        ge=0,
    )
    ticks: int = Field(
        description=(
            "How many simulation ticks to project forward. One tick is "
            "5 minutes by default. Typical values: 6 (= 30 min, immediate "
            "tactical horizon), 24 (= 2 hr, planning horizon), 72 (= 6 hr, "
            "strategic). Larger values cost more compute and are noisier."
        ),
        gt=0,
        le=200,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Output schema
# ═══════════════════════════════════════════════════════════════════════════════


class ProjectedBurnCell(BaseModel):
    """One cell expected to be burning by the end of the projection."""

    row: int = Field(description="Row of the projected-burn cell.")
    col: int = Field(description="Column of the projected-burn cell.")
    ignites_at_tick: int = Field(
        description=(
            "Tick offset (relative to the start of the projection) at which "
            "this cell first ignited. 0 = ignition source. Lower numbers "
            "mean the fire reached it sooner."
        ),
    )
    distance_from_source_cells: float = Field(
        description="Straight-line distance from the ignition source.",
    )


class SimulateSpreadFromOutput(BaseModel):
    """Tool result — the projected fire footprint."""

    projected_cells: list[ProjectedBurnCell] = Field(
        description=(
            "Cells projected to be burning by the end of the run, including "
            "the source. Sorted by ignites_at_tick ascending."
        ),
    )
    total_burned_cells: int = Field(description="Count of cells in projected_cells.")
    ticks_simulated: int = Field(description="Echo of the ticks parameter, for clarity.")
    direction_of_advance_deg: float | None = Field(
        description=(
            "Compass bearing (degrees, 0=N, 90=E) of the centroid of the "
            "burned area relative to the source. None if the fire did not "
            "spread beyond the source cell."
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════════


def make_simulate_spread_from(
    *,
    world_grid: GenericTerrainGrid,
    physics: RothermelFirePhysicsModule,
) -> StructuredTool:
    """Build the simulate_spread_from tool.

    The factory takes the live world_grid and physics module — but the
    inner function deepcopies the grid before running, so the live
    simulation is not affected.
    """

    @tool("simulate_spread_from", args_schema=SimulateSpreadFromInput)
    def simulate_spread_from(
        cell_row: int,
        cell_col: int,
        ticks: int,
    ) -> SimulateSpreadFromOutput:
        """Project where a fire would spread if a cell ignited right now.

        This is a HYPOTHETICAL query — it does not actually ignite anything
        in the live world. It runs the Rothermel spread model on a copy of
        the current world state for ``ticks`` ticks and returns the cells
        that would be burning at the end of the run.

        Use this tool when planning resource positioning: knowing *where*
        a fire is heading is essential to decide where to stage crews and
        which cells to defend. Pair it with get_resources_within to check
        whether reachable resources can intercept the projected path.

        The projection reflects current wind, fuel moisture, slope, and
        fuel model conditions in each cell. It does not account for any
        suppression actions the agent might recommend.

        Returns
        ───────
        SimulateSpreadFromOutput with:
          - ``projected_cells``: list of cells expected to be burning at
            the end of the run, each with the tick at which it first
            ignited and its distance from the source.
          - ``total_burned_cells``: convenience count.
          - ``ticks_simulated``: echo of the input.
          - ``direction_of_advance_deg``: compass bearing of the spread
            (None if no spread).
        """
        # ── IMPLEMENTATION GUIDE ────────────────────────────────────────
        #
        # Closes over: ``world_grid`` (GenericTerrainGrid), ``physics``
        #              (RothermelFirePhysicsModule).
        #
        # Step 1. Copy the grid so the live simulation is untouched.
        #   import copy
        #   sim_grid = copy.deepcopy(world_grid)
        #
        #   IMPORTANT: only deepcopy if the grid is small enough that
        #   the cost is acceptable. For a 100x100 grid this is fine; for
        #   larger maps consider a per-cell snapshot approach (record
        #   only the cells you mutate, restore them at the end). Defer
        #   that optimisation until measurements demand it.
        #
        # Step 2. Validate the source cell exists and is ignitable.
        #   - cell = sim_grid.get_cell(cell_row, cell_col)
        #   - If terrain is WATER or already-burning, return an empty
        #     projection with direction_of_advance_deg=None (don't raise —
        #     the LLM should be able to tell from the output that nothing
        #     happened, without the call surfacing as a tool error).
        #
        # Step 3. Ignite the source cell.
        #   The exact API depends on FireCellState — look at how the
        #   live simulation seeds ignitions (see scenario_loader.py for
        #   the "ignition" list it injects at scenario start). Mirror
        #   that: set state to FireState.BURNING, record ignition tick=0.
        #
        # Step 4. Track ignition ticks per cell as you go.
        #   ignition_ticks: dict[tuple[int, int], int] = {(cell_row, cell_col): 0}
        #
        # Step 5. Run the physics for `ticks` iterations.
        #   for t in range(1, ticks + 1):
        #       events = physics.tick_physics(sim_grid, ...)
        #       for cell that newly ignited this tick:
        #           ignition_ticks[(r, c)] = t
        #
        #   The exact loop body depends on what tick_physics() yields/
        #   returns — read its signature (line 100 in rothermel_physics.py)
        #   and match it. You may need to pass an environment object;
        #   in that case use the live environment from the world (it's
        #   stable across the projection).
        #
        # Step 6. Build the projected_cells list.
        #   For each (r, c), tick in ignition_ticks:
        #       distance = math.sqrt((r - cell_row)**2 + (c - cell_col)**2)
        #       Append ProjectedBurnCell(row=r, col=c, ignites_at_tick=tick,
        #                                distance_from_source_cells=distance)
        #   Sort by ignites_at_tick ascending.
        #
        # Step 7. Compute direction_of_advance_deg.
        #   If only the source ignited: None.
        #   Else: compute centroid of the non-source cells, then the
        #   bearing from source to centroid using:
        #       dr = centroid_row - cell_row    # negative = north
        #       dc = centroid_col - cell_col    # negative = west
        #       bearing = (math.degrees(math.atan2(dc, -dr))) % 360
        #   (atan2 with -dr because grid row=0 is north and increases
        #   southward; we want compass bearing where north=0.)
        #
        # Step 8. Return SimulateSpreadFromOutput.
        #
        # ────────────────────────────────────────────────────────────────
        raise NotImplementedError(
            "Implement per the IMPLEMENTATION GUIDE above. "
            "Closes over `world_grid` and `physics` provided by the factory. "
            "Critical: deepcopy the grid before running — never mutate live state."
        )

    return simulate_spread_from


__all__ = [
    "ProjectedBurnCell",
    "SimulateSpreadFromInput",
    "SimulateSpreadFromOutput",
    "make_simulate_spread_from",
]
