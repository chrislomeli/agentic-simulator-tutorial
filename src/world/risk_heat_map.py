"""RiskHeatMap — grid-aligned risk state for supervisor/resource planning.

Design:
- Mirrors terrain grid dimensions exactly (1:1 mapping)
- Updated by risk graph after cluster agent evaluations
- Read by supervisor for resource allocation decisions
- In-memory only for POC (DB persistence in v2 backlog)

LAYER REGISTRATION PATTERN:
The grid is the authority. All overlay layers (sensors, risk, resources)
validate positions via grid.register_layer() before registration.

POC v1 SCOPE:
- Risk scores only (0-10)
- Confidence levels (0-3)
- Assessment timestamps
- Dirty flags for incremental updates

BACKLOG:
- Persistence: store heat map snapshots in DB for trend analysis
- Multi-timescale risk (1-min urgent, 5-min sustained, 1-hour pattern)
- Derived features: risk gradients, spread prediction
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.commons.schemas import CollatedRecordRisk, GridPosition

logger = logging.getLogger(__name__)


@dataclass
class CellRiskState:
    """Current risk state for a single grid cell.
    
    This is what the supervisor/resource agent sees when making
    allocation decisions. Minimal, derived, just-in-time.
    """
    risk_score: int = 0           # 0-10, 0 = baseline/no assessment
    confidence: int = 0           # 0-3, 0 = no data yet
    assessed_at: datetime | None = None  # Last evaluation timestamp
    dirty: bool = False           # Modified since last read
    
    # POC v1: Skip trend history (in-memory only, no persistence)
    # BACKLOG: Add risk_score_history (circular buffer) for trend analysis
    # risk_history: deque[tuple[datetime, int]] = field(default_factory=lambda: deque(maxlen=100))
    
    def mark_dirty(self) -> None:
        """Mark cell as modified (trigger for re-evaluation)."""
        self.dirty = True
    
    def mark_clean(self) -> None:
        """Mark cell as read/processed."""
        self.dirty = False
    
    def is_hotspot(self, threshold: int = 7, min_confidence: int = 2) -> bool:
        """Check if this cell exceeds risk threshold with sufficient confidence."""
        return self.risk_score >= threshold and self.confidence >= min_confidence


class RiskHeatMap:
    """Grid-aligned risk state layer. Updated by risk graph, read by supervisor.
    
    MEMORY BOUNDS:
    - 100x100 grid = 10,000 CellRiskState objects
    - Each ~48 bytes = ~480KB total
    - 1000x1000 grid = 1M cells = ~48MB (still reasonable)
    
    COORDINATION:
    - Created by scenario_loader with same dimensions as terrain grid
    - Updated by cluster agent after LLM/stub risk assessment
    - Queried by supervisor for resource allocation
    """
    
    def __init__(self, rows: int, cols: int, layers: int = 1) -> None:
        """Initialize heat map with baseline risk (0) for all cells.
        
        Parameters
        ----------
        rows, cols : Grid dimensions (must match terrain grid)
        layers : Vertical layers (default 1 for 2D scenarios)
        """
        self._rows = rows
        self._cols = cols
        self._layers = layers
        
        # Initialize all cells with baseline state
        # 3D grid: layers × rows × cols
        self._grid: list[list[list[CellRiskState]]] = [
            [
                [CellRiskState() for _ in range(cols)]
                for _ in range(rows)
            ]
            for _ in range(layers)
        ]
        
        logger.info("Initialized RiskHeatMap: %dx%dx%d cells (all baseline risk=0)", 
                   rows, cols, layers)
    
    @property
    def rows(self) -> int:
        return self._rows
    
    @property
    def cols(self) -> int:
        return self._cols
    
    @property
    def layers(self) -> int:
        return self._layers
    
    def _is_valid_position(self, row: int, col: int, layer: int = 0) -> bool:
        """Check if position is within grid bounds."""
        return (0 <= row < self._rows and 
                0 <= col < self._cols and 
                0 <= layer < self._layers)
    
    def get(self, row: int, col: int, layer: int = 0) -> CellRiskState | None:
        """Get risk state for a specific cell."""
        if not self._is_valid_position(row, col, layer):
            return None
        return self._grid[layer][row][col]
    
    def update_from_assessment(self, risk: CollatedRecordRisk) -> bool:
        """Update cell risk state from a cluster agent assessment.
        
        Called by the risk graph after LLM/stub evaluation.
        
        Parameters
        ----------
        risk : CollatedRecordRisk from cluster agent
        
        Returns
        -------
        True if update successful, False if position out of bounds
        """
        pos = risk.position
        if not self._is_valid_position(pos.row, pos.col, pos.layer):
            logger.warning(
                "Risk assessment for (%d, %d, %d) outside heat map bounds (%d, %d, %d)",
                pos.row, pos.col, pos.layer, self._rows, self._cols, self._layers
            )
            return False
        
        cell = self._grid[pos.layer][pos.row][pos.col]
        cell.risk_score = risk.risk_score
        cell.confidence = risk.confidence
        cell.assessed_at = datetime.now()
        cell.mark_dirty()
        
        # POC v1: Skip history tracking
        # BACKLOG: cell.risk_history.append((cell.assessed_at, risk.risk_score))
        
        return True
    
    def get_hotspots(self, threshold: int = 7, min_confidence: int = 2) -> list[tuple[int, int, int, CellRiskState]]:
        """Get all cells at or above risk threshold with sufficient confidence.
        
        For supervisor resource allocation: "Where are the fires?"
        
        Returns
        -------
        List of (row, col, layer, cell_state) tuples, sorted by risk_score desc
        """
        hotspots = []
        for layer in range(self._layers):
            for row in range(self._rows):
                for col in range(self._cols):
                    cell = self._grid[layer][row][col]
                    if cell.risk_score >= threshold and cell.confidence >= min_confidence:
                        hotspots.append((row, col, layer, cell))
        
        # Sort by risk score descending (most urgent first)
        hotspots.sort(key=lambda x: x[3].risk_score, reverse=True)
        return hotspots
    
    def get_dirty_cells(self) -> list[tuple[int, int, int, CellRiskState]]:
        """Get all cells modified since last read/clean operation.
        
        For incremental updates: "What changed since I last looked?"
        """
        dirty = []
        for layer in range(self._layers):
            for row in range(self._rows):
                for col in range(self._cols):
                    cell = self._grid[layer][row][col]
                    if cell.dirty:
                        dirty.append((row, col, layer, cell))
        return dirty
    
    def mark_all_clean(self) -> None:
        """Mark all cells as clean (call after processing dirty cells)."""
        for layer in self._grid:
            for row in layer:
                for cell in row:
                    cell.mark_clean()
    
    def snapshot(self) -> list[list[list[CellRiskState]]]:
        """Return full grid snapshot (marking all cells as clean).
        
        For supervisor heat map visualization.
        """
        self.mark_all_clean()
        return self._grid
    
    def get_summary_stats(self) -> dict:
        """Get aggregate statistics for dashboard/monitoring.
        
        Returns
        -------
        Dict with: total_cells, assessed_cells, hotspot_count, 
                  avg_risk, max_risk, cells_by_confidence_level
        """
        total = self._rows * self._cols * self._layers
        assessed = 0
        hotspots = 0
        risk_sum = 0
        max_risk = 0
        confidence_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        
        for layer in self._grid:
            for row in layer:
                for cell in row:
                    if cell.assessed_at is not None:
                        assessed += 1
                        risk_sum += cell.risk_score
                        max_risk = max(max_risk, cell.risk_score)
                        if cell.is_hotspot():
                            hotspots += 1
                    confidence_counts[cell.confidence] += 1
        
        return {
            "total_cells": total,
            "assessed_cells": assessed,
            "hotspot_count": hotspots,
            "avg_risk": risk_sum / assessed if assessed > 0 else 0,
            "max_risk": max_risk,
            "coverage_pct": (assessed / total * 100) if total > 0 else 0,
            "confidence_distribution": confidence_counts,
        }
    
    def reset(self) -> None:
        """Reset all cells to baseline (risk=0, confidence=0).
        
        For scenario restart or testing.
        """
        for layer in self._grid:
            for row in layer:
                for cell in row:
                    cell.risk_score = 0
                    cell.confidence = 0
                    cell.assessed_at = None
                    cell.mark_clean()
        logger.info("RiskHeatMap reset to baseline")


def create_risk_heat_map(rows: int, cols: int, layers: int = 1) -> RiskHeatMap:
    """Factory: Create heat map matching terrain grid dimensions.
    
    Called by scenario_loader to ensure 1:1 mapping with terrain.
    """
    return RiskHeatMap(rows=rows, cols=cols, layers=layers)
