"""
world-simulator.agents.logistics.tools.wind_history

Tool: get_wind_history
──────────────────────
Lets the logistics LLM ask: "what has wind speed and direction looked
like at this cell over the last N ticks?"

Why this matters for logistics
──────────────────────────────
A fire's behavior is dominated by wind. The single most dangerous
condition for crews is a wind shift — the fire that was pushing east
suddenly pushes north, and crews positioned on the north flank become
the head of the fire. Knowing the *current* wind isn't enough; the
LLM needs to see whether wind has been steady, gusting, or rotating.

The risk agent's CollatedRecord contains the *latest* wind reading
only. This tool exposes the temporal dimension.

Backing infrastructure (NOT YET IMPLEMENTED)
────────────────────────────────────────────
``CellStateManager`` currently keeps only the latest metric per type
per cell. To answer historical questions, ``_CellSnapshot`` needs a
ring buffer. See ``tools/README.md`` § Open infrastructure TODOs for
the suggested shape — a bounded ``deque`` per metric type, appended
to inside ``_CellSnapshot.update_metric``.

Until that ring buffer exists, this tool will raise NotImplementedError
with a pointer to the README. The schema is finalized so that wiring
the agent does not have to wait for the buffer.
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field

from world.cell_state_manager import CellStateManager

# ═══════════════════════════════════════════════════════════════════════════════
# Input schema
# ═══════════════════════════════════════════════════════════════════════════════


class GetWindHistoryInput(BaseModel):
    """Arguments Claude provides when calling get_wind_history."""

    cell_row: int = Field(description="Row of the cell to query.", ge=0)
    cell_col: int = Field(description="Column of the cell to query.", ge=0)
    samples: int = Field(
        description=(
            "How many recent samples to return (most recent first). "
            "Typical: 10 for a quick variability check, 30 for a longer "
            "trend window. Bounded by the underlying ring buffer's max "
            "length, so passing a very large number returns whatever is "
            "available."
        ),
        gt=0,
        le=200,
        default=20,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Output schema
# ═══════════════════════════════════════════════════════════════════════════════


class WindSample(BaseModel):
    """One historical wind reading."""

    timestamp: datetime = Field(description="When the reading was recorded (UTC).")
    speed_mps: float | None = Field(
        description="Wind speed in metres per second. None if no reading at this timestamp.",
    )
    direction_deg: float | None = Field(
        description=(
            "Wind direction in compass degrees (0=N, 90=E). The direction "
            "the wind is coming FROM, per meteorological convention. None "
            "if no reading at this timestamp."
        ),
    )


class GetWindHistoryOutput(BaseModel):
    """Tool result — a time series of recent wind readings, plus quick stats."""

    samples: list[WindSample] = Field(
        description=(
            "Wind readings ordered most-recent-first. May be shorter than "
            "the requested length if the buffer hasn't filled."
        ),
    )
    speed_mean_mps: float | None = Field(
        description="Mean speed across returned samples. None if empty.",
    )
    speed_stddev_mps: float | None = Field(
        description=(
            "Standard deviation of speed across returned samples. Useful "
            "for detecting gusty conditions. None if fewer than 2 samples."
        ),
    )
    direction_stddev_deg: float | None = Field(
        description=(
            "Circular standard deviation of direction across returned "
            "samples (in degrees). High values signal a rotating or "
            "variable wind — particularly dangerous for crew positioning. "
            "None if fewer than 2 samples."
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════════


def make_get_wind_history(*, cell_state_manager: CellStateManager) -> StructuredTool:
    """Build the get_wind_history tool, bound to a live CellStateManager.

    Depends on a ring buffer in ``_CellSnapshot`` that does not exist yet.
    See ``tools/README.md`` for the suggested implementation. Once the
    buffer is added, the inner function can read from
    ``snap.metric_history["wind_speed"]`` and ``["wind_direction"]``.
    """

    @tool("get_wind_history", args_schema=GetWindHistoryInput)
    def get_wind_history(
        cell_row: int,
        cell_col: int,
        samples: int = 20,
    ) -> GetWindHistoryOutput:
        """Return recent wind speed and direction readings for a cell.

        Use this tool when wind variability matters for response planning —
        for example, when deciding where to stage crews relative to an
        active or projected fire. A steady wind from one direction allows
        confident flank positioning; a rotating or gusty wind means crews
        must be positioned more conservatively.

        Returned samples are ordered most-recent-first. The result includes
        circular standard deviation of direction, which is the single most
        useful number for "is this wind reliable?" — values under ~15° are
        steady, 15–45° is variable, above 45° is essentially rotating.

        If the cell has no history yet (e.g. a brand-new sensor or a cell
        outside any sensor's reach), returns an empty samples list with
        all stats set to None — call this out in your reasoning rather
        than treating it as missing raw.

        Returns
        ───────
        GetWindHistoryOutput with:
          - ``samples``: time series of (timestamp, speed_mps, direction_deg).
          - ``speed_mean_mps``, ``speed_stddev_mps``: speed stats.
          - ``direction_stddev_deg``: circular stddev of direction. The
            primary "is wind steady?" signal.
        """
        # ── IMPLEMENTATION GUIDE ────────────────────────────────────────
        #
        # Closes over: ``cell_state_manager`` (CellStateManager).
        #
        # PRE-REQUISITE: a ring buffer on _CellSnapshot. See
        # tools/README.md § Open infrastructure TODOs for the suggested
        # shape. Until that lands, this function raises NotImplementedError.
        #
        # Once the buffer exists, the implementation is:
        #
        # Step 1. Look up the cell's snapshot.
        #   snap = cell_state_manager.get_snapshot(cell_row, cell_col)
        #   if snap is None:
        #       return GetWindHistoryOutput(samples=[], speed_mean_mps=None,
        #                                   speed_stddev_mps=None,
        #                                   direction_stddev_deg=None)
        #
        # Step 2. Pull the two ring buffers.
        #   speed_history = snap.metric_history.get("wind_speed", deque())
        #   dir_history   = snap.metric_history.get("wind_direction", deque())
        #
        # Step 3. Align them.
        #   The two metrics are recorded together (one wind event produces
        #   both wind_speed and wind_direction with the same timestamp),
        #   so iterating in lock-step is correct. If one buffer has fewer
        #   entries than the other (unlikely but possible during startup),
        #   align by timestamp and emit None for the missing field.
        #
        # Step 4. Take the most recent ``samples`` entries.
        #   pairs = list(zip(speed_history, dir_history))[-samples:]
        #   pairs.reverse()  # most-recent-first per the schema contract
        #
        # Step 5. Build the WindSample list.
        #   wind_samples = [
        #       WindSample(timestamp=ts, speed_mps=spd, direction_deg=dirn)
        #       for (ts, spd), (_, dirn) in pairs
        #   ]
        #
        # Step 6. Compute stats.
        #   speeds = [s for s in (w.speed_mps for w in wind_samples) if s is not None]
        #   dirs   = [d for d in (w.direction_deg for w in wind_samples) if d is not None]
        #
        #   speed_mean = statistics.fmean(speeds) if speeds else None
        #   speed_std  = statistics.stdev(speeds) if len(speeds) >= 2 else None
        #
        #   direction_stddev_deg requires CIRCULAR statistics — directions
        #   are an angle, not a scalar. A naive stdev on [350, 10, 5] gives
        #   a huge number even though those are all roughly north. Use:
        #
        #       import math
        #       sin_sum = sum(math.sin(math.radians(d)) for d in dirs)
        #       cos_sum = sum(math.cos(math.radians(d)) for d in dirs)
        #       n = len(dirs)
        #       R = math.sqrt(sin_sum**2 + cos_sum**2) / n
        #       # circular variance = 1 - R, in radians^2-ish
        #       dir_std_rad = math.sqrt(-2.0 * math.log(R)) if R > 0 else float("inf")
        #       dir_std_deg = math.degrees(dir_std_rad) if len(dirs) >= 2 else None
        #
        #   This is the Mardia-Jupp circular stddev. Cap at some sensible
        #   value (e.g. 180.0) to avoid float("inf") leaking into the LLM
        #   prompt.
        #
        # Step 7. Return GetWindHistoryOutput.
        #
        # ────────────────────────────────────────────────────────────────
        raise NotImplementedError(
            "Implement per the IMPLEMENTATION GUIDE above. "
            "Requires a ring buffer on _CellSnapshot — see "
            "src/agents/logistics/tools/README.md § Open infrastructure TODOs."
        )

    return get_wind_history


__all__ = [
    "GetWindHistoryInput",
    "GetWindHistoryOutput",
    "WindSample",
    "make_get_wind_history",
]
