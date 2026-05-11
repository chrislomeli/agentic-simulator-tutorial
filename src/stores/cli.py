"""CLI harness for testing DB fetch operations.

Usage:
    python -m stores.cli sensors --region lpnf_south --limit 10
    python -m stores.cli terrain --region lpnf_south --limit 100
    python -m stores.cli wildfires --min-acres 1000 --max-acres 5000 --limit 5
"""

from __future__ import annotations

import argparse
import sys
import atexit
from typing import Sequence

from stores import (
    SensorRepository,
    TerrainRepository,
    WildfireRepository,
    get_pg_gateway,
)

# Global for cleanup
_gateway = None

def _cleanup_gateway():
    """Close the connection pool on exit."""
    global _gateway
    if _gateway is not None:
        _gateway.close()

atexit.register(_cleanup_gateway)


def cmd_sensors(args: argparse.Namespace) -> int:
    """Fetch and display sensors for a region."""
    global _gateway
    _gateway = get_pg_gateway()
    repo = SensorRepository(_gateway)

    inventory = repo.fetch_sensors(
        region_name=args.region,
        grid_rows=args.rows,
        grid_cols=args.cols,
        grid_layers=args.layers,
        limit=args.limit,
    )

    print(f"\nSensors for region '{args.region}' ({args.rows}x{args.cols}x{args.layers} grid):")
    print(f"Total loaded: {inventory.size}\n")

    # Show first few sensors
    sensors = list(inventory.all_sensors())[: args.show]
    for sensor in sensors:
        pos = sensor.location
        print(f"  {sensor.source_id:20s} {sensor.source_type:15s} @ ({pos.row}, {pos.col}, {pos.layer})")

    if inventory.size > args.show:
        print(f"  ... and {inventory.size - args.show} more")

    return 0


def cmd_terrain(args: argparse.Namespace) -> int:
    """Fetch and display terrain for a region."""
    global _gateway
    _gateway = get_pg_gateway()
    repo = TerrainRepository(_gateway)

    terrain_dict, config = repo.fetch_terrain(
        region_name=args.region,
        limit=args.limit,
    )

    print(f"\nTerrain for region '{args.region}':")
    print(f"Total cells: {len(terrain_dict)}")
    print(f"Physics config: cell_size_ft={config.cell_size_ft}, "
          f"time_step_min={config.time_step_min}, "
          f"burn_duration_ticks={config.burn_duration_ticks}")
    print()

    # Show first few cells
    items = list(terrain_dict.items())[: args.show]
    for (row, col, layer), terrain in items:
        print(f"  ({row:3d}, {col:3d}, {layer}) {terrain.terrain:10s} "
              f"veg={terrain.vegetation:.2f} moist={terrain.fuel_moisture:.2f} "
              f"slope={terrain.slope:.2f}")

    if len(terrain_dict) > args.show:
        print(f"  ... and {len(terrain_dict) - args.show} more cells")

    return 0


def cmd_wildfires(args: argparse.Namespace) -> int:
    """Fetch and display historical wildfire data."""
    global _gateway
    _gateway = get_pg_gateway()
    repo = WildfireRepository(_gateway)

    if args.name:
        fires = repo.fetch_by_fire_name(
            fire_name=args.name,
            limit=args.limit,
        )
        print(f"\nHistorical fires matching '{args.name}':")
    else:
        fires = repo.fetch_similar_fires(
            min_acres=args.min_acres,
            max_acres=args.max_acres,
            limit=args.limit,
        )
        print(f"\nHistorical fires between {args.min_acres} and {args.max_acres} acres:")

    print(f"Total found: {len(fires)}\n")

    for fire in fires:
        date_str = fire.imsr_date.strftime("%Y-%m-%d") if fire.imsr_date else "unknown"
        print(f"  {date_str} | {fire.fire_name:30s} | "
              f"{fire.fire_size_acres or '?':>8s} acres | "
              f"personnel={fire.personnel or 0:>4d} engines={fire.engines or 0:>3d}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stores.cli",
        description="CLI harness for testing DB fetch operations",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # sensors command
    sensors_parser = subparsers.add_parser("sensors", help="Fetch sensors for a region")
    sensors_parser.add_argument("--region", required=True, help="Region name (e.g., lpnf_south)")
    sensors_parser.add_argument("--rows", type=int, default=50, help="Grid rows (default: 50)")
    sensors_parser.add_argument("--cols", type=int, default=50, help="Grid columns (default: 50)")
    sensors_parser.add_argument("--layers", type=int, default=1, help="Grid layers (default: 1)")
    sensors_parser.add_argument("--limit", type=int, default=None, help="Max sensors to load")
    sensors_parser.add_argument("--show", type=int, default=20, help="Number to display (default: 20)")
    sensors_parser.set_defaults(func=cmd_sensors)

    # terrain command
    terrain_parser = subparsers.add_parser("terrain", help="Fetch terrain for a region")
    terrain_parser.add_argument("--region", required=True, help="Region name (e.g., lpnf_south)")
    terrain_parser.add_argument("--limit", type=int, default=None, help="Max cells to load")
    terrain_parser.add_argument("--show", type=int, default=20, help="Number to display (default: 20)")
    terrain_parser.set_defaults(func=cmd_terrain)

    # wildfires command
    wildfires_parser = subparsers.add_parser("wildfires", help="Fetch historical wildfire data")
    wildfires_parser.add_argument("--min-acres", type=int, default=0, help="Min fire size (default: 0)")
    wildfires_parser.add_argument("--max-acres", type=int, default=100000, help="Max fire size (default: 100000)")
    wildfires_parser.add_argument("--name", type=str, default=None, help="Search by fire name (fuzzy match)")
    wildfires_parser.add_argument("--limit", type=int, default=10, help="Max records (default: 10)")
    wildfires_parser.set_defaults(func=cmd_wildfires)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
