"""
ogar.domains.wildfire.nwcg_resources

NWCG (National Wildfire Coordinating Group) standard resource catalog and
fireline intensity thresholds for resource typing.

This formalises the raw data from docs/tutorial/wildfires/resources.py into
typed dataclasses that the resource-sizing tools can query programmatically.

NWCG resource typing uses integer type numbers where 1 = heaviest/most capable
and higher numbers = lighter/less capable (e.g. Type-1 hotshot > Type-2 hand crew).

Fireline intensity thresholds source:
  Rothermel (1972), Byram (1959), NWCG Incident Response Pocket Guide (IRPG).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Resource specification ────────────────────────────────────────────────────

@dataclass(frozen=True)
class NWCGResourceSpec:
    """
    NWCG standard resource specification.

    Attributes
    ──────────
    nwcg_id                    : Alphanumeric NWCG identifier (e.g. "C-1", "E-3")
    kind                       : Resource kind (e.g. "Crew", "Engine", "Helicopter")
    nwcg_type                  : NWCG type number — 1 = heaviest/most capable
    name                       : Full NWCG name
    category                   : "Personnel", "Equipment", "Aircraft", or "Cache-*"
    production_rate_chains_hr  : Fireline construction rate (chains/hr) — crews and dozers
    tank_gal                   : Water tank capacity (gallons) — engines and tenders
    pump_gpm                   : Pump rate (gallons/minute) — engines and tenders
    capacity_gal               : Drop/bucket capacity (gallons) — aircraft
    """
    nwcg_id: str
    kind: str
    nwcg_type: int | str          # int for operational resources, str for cache items
    name: str
    category: str
    production_rate_chains_hr: Optional[float] = None
    tank_gal: Optional[float] = None
    pump_gpm: Optional[float] = None
    capacity_gal: Optional[float] = None


# ── NWCG catalog ──────────────────────────────────────────────────────────────
# Source: docs/tutorial/wildfires/resources.py

NWCG_CATALOG: List[NWCGResourceSpec] = [
    # ── Personnel ─────────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="C-1",
        kind="Crew",
        nwcg_type=1,
        name="Interagency Hotshot Crew (IHC)",
        category="Personnel",
        production_rate_chains_hr=15.0,
    ),
    NWCGResourceSpec(
        nwcg_id="C-2",
        kind="Crew",
        nwcg_type=2,
        name="Hand Crew",
        category="Personnel",
        production_rate_chains_hr=8.0,
    ),
    NWCGResourceSpec(
        nwcg_id="C-10",
        kind="Smokejumpers",
        nwcg_type=1,
        name="Smokejumper Load",
        category="Personnel",
        production_rate_chains_hr=10.0,
    ),
    NWCGResourceSpec(
        nwcg_id="C-20",
        kind="Helitack",
        nwcg_type=2,
        name="Helitack Crew",
        category="Personnel",
        production_rate_chains_hr=5.0,
    ),

    # ── Engines ───────────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="E-1",
        kind="Engine",
        nwcg_type=1,
        name="Structure Engine",
        category="Equipment",
        tank_gal=300.0,
        pump_gpm=1000.0,
    ),
    NWCGResourceSpec(
        nwcg_id="E-3",
        kind="Engine",
        nwcg_type=3,
        name="Wildland Engine (4x4)",
        category="Equipment",
        tank_gal=500.0,
        pump_gpm=150.0,
    ),
    NWCGResourceSpec(
        nwcg_id="E-6",
        kind="Engine",
        nwcg_type=6,
        name="Wildland Brush Truck",
        category="Equipment",
        tank_gal=150.0,
        pump_gpm=50.0,
    ),

    # ── Dozers ────────────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="D-1",
        kind="Dozer",
        nwcg_type=1,
        name="Heavy Dozer (D8/D7)",
        category="Equipment",
        production_rate_chains_hr=60.0,
    ),
    NWCGResourceSpec(
        nwcg_id="D-3",
        kind="Dozer",
        nwcg_type=3,
        name="Light Dozer (D4/D5)",
        category="Equipment",
        production_rate_chains_hr=30.0,
    ),

    # ── Water Tenders ─────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="WT-1",
        kind="Water Tender",
        nwcg_type=1,
        name="Tactical Water Tender",
        category="Equipment",
        tank_gal=2000.0,
        pump_gpm=250.0,
    ),
    NWCGResourceSpec(
        nwcg_id="WT-2",
        kind="Water Tender",
        nwcg_type=2,
        name="Support Water Tender",
        category="Equipment",
        tank_gal=4000.0,
        pump_gpm=200.0,
    ),

    # ── Air Tankers ───────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="A-1",
        kind="Air Tanker",
        nwcg_type=1,
        name="Large Air Tanker (LAT)",
        category="Aircraft",
        capacity_gal=3000.0,
    ),
    NWCGResourceSpec(
        nwcg_id="A-2",
        kind="Air Tanker",
        nwcg_type=2,
        name="Very Large Air Tanker (VLAT)",
        category="Aircraft",
        capacity_gal=9400.0,
    ),

    # ── Helicopters ───────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="H-1",
        kind="Helicopter",
        nwcg_type=1,
        name="Heavy Helicopter (Type 1)",
        category="Aircraft",
        capacity_gal=700.0,
    ),
    NWCGResourceSpec(
        nwcg_id="H-3",
        kind="Helicopter",
        nwcg_type=3,
        name="Light Helicopter (Type 3)",
        category="Aircraft",
        capacity_gal=100.0,
    ),

    # ── Cache items ───────────────────────────────────────────────────────────
    NWCGResourceSpec(
        nwcg_id="NFES-0670",
        kind="Pump",
        nwcg_type="Mark-3",
        name="Portable High Pressure Pump",
        category="Cache-Trackable",
    ),
    NWCGResourceSpec(
        nwcg_id="NFES-0007",
        kind="Safety",
        nwcg_type="Shelter",
        name="Fire Shelter (Standard)",
        category="Cache-Durable",
    ),
    NWCGResourceSpec(
        nwcg_id="NFES-1230",
        kind="Hose",
        nwcg_type="1.5 inch",
        name="Lined Fire Hose",
        category="Cache-Durable",
    ),
    NWCGResourceSpec(
        nwcg_id="NFES-0606",
        kind="Chemical",
        nwcg_type="Retardant",
        name="Phos-Chek Retardant Powder",
        category="Cache-Consumable",
    ),
    NWCGResourceSpec(
        nwcg_id="NFES-0715",
        kind="Food",
        nwcg_type="MRE",
        name="Meals Ready to Eat",
        category="Cache-Consumable",
    ),
]


# ── Fireline intensity thresholds (BTU/ft/s) ─────────────────────────────────
#
# These thresholds determine which resource types can effectively engage a fire
# at a given fireline intensity level.
#
# Source: Rothermel (1972), Byram (1959), NWCG IRPG operational guidelines.
# Rule of thumb:
#   <   100 BTU/ft/s  → hand crews can work the line directly
#   <   500 BTU/ft/s  → engines effective for direct attack
#   <  1000 BTU/ft/s  → heavy dozers can construct fireline
#   < 2000 BTU/ft/s   → aerial retardant effective
#   ≥  2000 BTU/ft/s  → indirect attack only; direct suppression marginal

INTENSITY_THRESHOLDS: Dict[str, float] = {
    "hand_crew": 100.0,   # BTU/ft/s — hand crews effective below this
    "engine":    500.0,   # BTU/ft/s — engines effective below this
    "dozer":    1000.0,   # BTU/ft/s — dozers effective below this
    "air_tanker": 2000.0, # BTU/ft/s — aerial marginal above this
}


# ── Catalog helpers ───────────────────────────────────────────────────────────

def get_by_id(nwcg_id: str) -> Optional[NWCGResourceSpec]:
    """Look up a resource spec by NWCG ID (e.g. "C-1")."""
    for spec in NWCG_CATALOG:
        if spec.nwcg_id == nwcg_id:
            return spec
    return None


def get_by_kind(kind: str) -> List[NWCGResourceSpec]:
    """Return all specs for a given kind (e.g. "Crew", "Engine", "Dozer")."""
    return [s for s in NWCG_CATALOG if s.kind == kind]


def suppression_category(intensity_btu_ft_s: float) -> str:
    """
    Return the suppression difficulty category for a given fireline intensity.

    Categories (from NWCG operational guidelines):
      hand_crew        : intensity < 100 BTU/ft/s
      engine           : 100 ≤ intensity < 500 BTU/ft/s
      dozer            : 500 ≤ intensity < 1000 BTU/ft/s
      aerial_only      : 1000 ≤ intensity < 2000 BTU/ft/s
      beyond_suppression: intensity ≥ 2000 BTU/ft/s
    """
    if intensity_btu_ft_s < INTENSITY_THRESHOLDS["hand_crew"]:
        return "hand_crew"
    if intensity_btu_ft_s < INTENSITY_THRESHOLDS["engine"]:
        return "engine"
    if intensity_btu_ft_s < INTENSITY_THRESHOLDS["dozer"]:
        return "dozer"
    if intensity_btu_ft_s < INTENSITY_THRESHOLDS["air_tanker"]:
        return "aerial_only"
    return "beyond_suppression"
