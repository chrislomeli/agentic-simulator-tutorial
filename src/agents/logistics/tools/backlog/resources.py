"""
world-simulator.agents.logistics.tools.resources

Tool: get_resources_within
──────────────────────────
Lets the logistics LLM ask: "what crews/engines are reachable within
N minutes of cell (r, c)?"

Backed by ``ResourceInventory`` — the inventory tracks where each
resource is placed and its current operational status. This tool walks
that inventory, computes travel time for each candidate, filters by
status and time budget, and returns a ranked list.

Design notes
────────────
The tool deliberately does NOT decide what resources are *needed* —
that is the LLM's reasoning job. It only reports what is *available
and reachable*. The LLM sees this list, weighs it against the spread
projection and the risk assessment, and produces a deployment plan.

Travel time is computed from straight-line grid distance. A more
faithful model (road network, terrain traversal cost, mobility class)
would belong inside ``ResourceInventory`` or a dedicated routing
service — keep it out of the tool itself so the tool stays a thin
query layer.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field

from resources.base import ResourceStatus
from resources.inventory import ResourceInventory

# ═══════════════════════════════════════════════════════════════════════════════
# Input schema — what Claude must pass when calling this tool
# ═══════════════════════════════════════════════════════════════════════════════


class GetResourcesWithinInput(BaseModel):
    """Arguments Claude provides when calling get_resources_within."""

    cell_row: int = Field(
        description="Row of the cell at the center of the search (0-indexed, north=0).",
        ge=0,
    )
    cell_col: int = Field(
        description="Column of the cell at the center of the search (0-indexed, west=0).",
        ge=0,
    )
    max_minutes: float = Field(
        description=(
            "Maximum travel time budget in minutes. Resources whose ETA "
            "exceeds this are excluded. Typical values: 15 for immediate "
            "response, 60 for staged deployment, 240 for extended attack."
        ),
        gt=0.0,
    )
    cluster_id: str | None = Field(
        default=None,
        description=(
            "Optional cluster filter. If provided, only resources assigned "
            "to this cluster are considered. Pass None to search across all "
            "clusters (useful for mutual-aid scenarios)."
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Output schema — what the tool returns to Claude
# ═══════════════════════════════════════════════════════════════════════════════


class ReachableResource(BaseModel):
    """One resource that satisfied the search criteria."""

    resource_id: str = Field(description="Stable unique identifier, e.g. 'engine-12'.")
    resource_type: str = Field(description="Domain tag, e.g. 'engine', 'hand_crew', 'helicopter'.")
    grid_row: int = Field(description="Current row position of the resource.")
    grid_col: int = Field(description="Current column position of the resource.")
    distance_cells: float = Field(description="Straight-line distance in grid cells.")
    eta_minutes: float = Field(description="Estimated travel time in minutes.")
    status: str = Field(
        description="Operational status, e.g. 'AVAILABLE', 'EN_ROUTE', 'COMMITTED'.",
    )
    capacity: float = Field(description="Maximum capability (units depend on resource type).")
    available: float = Field(
        description="Remaining capability right now (0 ≤ available ≤ capacity).",
    )


class GetResourcesWithinOutput(BaseModel):
    """Tool result — the list of reachable resources, plus a small summary."""

    resources: list[ReachableResource] = Field(
        description="Reachable resources, sorted by ascending ETA then by capability rank.",
    )
    total_considered: int = Field(
        description="How many resources were inspected before filtering.",
    )
    excluded_unavailable: int = Field(
        description="How many were dropped because their status was not AVAILABLE.",
    )
    excluded_too_far: int = Field(
        description="How many were dropped because their ETA exceeded max_minutes.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Factory — closes over runtime deps and returns the tool
# ═══════════════════════════════════════════════════════════════════════════════


def make_get_resources_within(*, inventory: ResourceInventory) -> StructuredTool:
    """Build the get_resources_within tool, bound to a live ResourceInventory.

    Called once at agent-graph construction time. The returned StructuredTool
    is what gets passed to ``llm.bind_tools([...])`` and to ``ToolNode([...])``.
    """

    @tool("get_resources_within", args_schema=GetResourcesWithinInput)
    def get_resources_within(
        cell_row: int,
        cell_col: int,
        max_minutes: float,
        cluster_id: str | None = None,
    ) -> GetResourcesWithinOutput:
        """Find emergency response resources reachable within a time budget.

        Use this tool when planning a response to a hazardous cell — for
        example, after the risk agent has flagged a cell as high-risk and
        you need to know what crews and equipment can be deployed there.

        Returns resources whose status is AVAILABLE and whose estimated
        travel time to the target cell is at most ``max_minutes``. Results
        are sorted by ascending ETA, then by capability (more-capable
        resources first when ETAs tie).

        Note: this tool does NOT recommend *which* resources to deploy —
        it only reports what is reachable. Selection is your judgment.

        Returns
        ───────
        GetResourcesWithinOutput with:
          - ``resources``: list of reachable resources, each with id, type,
            position, distance, ETA, status, capacity, and current availability.
          - ``total_considered``, ``excluded_unavailable``, ``excluded_too_far``:
            counts so you can tell whether the empty-list case was "no crews
            exist" vs. "all crews are committed elsewhere" vs. "everyone is
            too far away".
        """
        # ── IMPLEMENTATION GUIDE ────────────────────────────────────────
        #
        # Closes over: ``inventory`` (ResourceInventory)
        #
        # Step 1. Pick the candidate set.
        #   - If cluster_id is None: ``inventory.all_resources()``
        #   - Else: ``inventory.by_cluster(cluster_id)``
        #
        # Step 2. Track counters as you walk:
        #   total_considered = len(candidates)
        #   excluded_unavailable = 0
        #   excluded_too_far = 0
        #
        # Step 3. For each candidate resource:
        #   a. Filter on status. Only keep ResourceStatus.AVAILABLE.
        #      Increment excluded_unavailable for the rest.
        #
        #   b. Compute straight-line grid distance:
        #         dr = resource.grid_row - cell_row
        #         dc = resource.grid_col - cell_col
        #         distance_cells = math.sqrt(dr*dr + dc*dc)
        #
        #   c. Compute ETA. For now, use a uniform travel speed assumption:
        #         MINUTES_PER_CELL = 2.0  # tune later or move to config
        #         eta_minutes = distance_cells * MINUTES_PER_CELL
        #      A real implementation would consult resource.metadata for
        #      a per-resource speed (a helicopter is much faster than an
        #      engine), but keep that out of v1 — the goal is to wire the
        #      tool, not perfect the routing.
        #
        #   d. Filter on max_minutes. If eta_minutes > max_minutes,
        #      increment excluded_too_far and continue.
        #
        #   e. Build a ReachableResource and append to a working list.
        #
        # Step 4. Sort the working list:
        #   - Primary key: eta_minutes ascending
        #   - Secondary key: capability rank — for now, resource.capacity
        #     descending. (NWCG type number would be better but requires
        #     joining against the catalog; defer.)
        #
        # Step 5. Return GetResourcesWithinOutput with the list and the
        #         three counters.
        #
        # ────────────────────────────────────────────────────────────────
        raise NotImplementedError(
            "Implement per the IMPLEMENTATION GUIDE above. "
            "Closes over `inventory` (ResourceInventory) provided by the factory."
        )

    return get_resources_within


# Make ResourceStatus available to implementers without an extra import line.
__all__ = [
    "GetResourcesWithinInput",
    "GetResourcesWithinOutput",
    "ReachableResource",
    "ResourceStatus",
    "make_get_resources_within",
]
