"""
lpnf_grid_to_csv.py
-------------------
Converts the lpnf-south scenario JSON file into a flat CSV of grid cells
with calculated lat/lon coordinates.

Usage:
    python lpnf_grid_to_csv.py <input_json> [output_csv]

    input_json  : path to your lpnf-south.json file
    output_csv  : (optional) output path, defaults to lpnf_grid_cells.csv

Example:
    python lpnf_grid_to_csv.py lpnf-south.json lpnf_grid_cells.csv
"""

import json
import csv
import sys
import os

# ---------------------------------------------------------------------------
# Configuration — pulled from the scenario JSON but also set as defaults here
# ---------------------------------------------------------------------------
LAT_MIN = 34.25
LAT_MAX = 35.15
LON_MIN = -119.95
LON_MAX = -118.45
ROWS = 50
COLS = 50

# Physics defaults (overridden by values in the JSON if present)
DEFAULT_CELL_SIZE_FT     = 6336
DEFAULT_TIME_STEP_MIN    = 5.0
DEFAULT_BURN_DURATION    = 10


def cell_lat(row, rows, lat_max, lat_min):
    """Row 0 = northernmost (lat_max), row N-1 = southernmost (lat_min)."""
    return round(lat_max - (row / (rows - 1)) * (lat_max - lat_min), 6)


def cell_lon(col, cols, lon_min, lon_max):
    """Col 0 = westernmost (lon_min), col N-1 = easternmost (lon_max)."""
    return round(lon_min + (col / (cols - 1)) * (lon_max - lon_min), 6)


def main():
    # ------------------------------------------------------------------
    # Argument handling
    # ------------------------------------------------------------------
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path  = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "lpnf_grid_cells.csv"

    if not os.path.exists(input_path):
        print(f"ERROR: input file not found: {input_path}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Load JSON
    # ------------------------------------------------------------------
    print(f"Loading {input_path} ...")
    with open(input_path, encoding="utf-8") as f:
        scenario = json.load(f)

    # ------------------------------------------------------------------
    # Extract grid parameters from JSON (fall back to defaults)
    # ------------------------------------------------------------------
    dims   = scenario.get("dimensions", {})
    bounds = scenario.get("bounds", {})
    phys   = scenario.get("physics", {})

    rows     = dims.get("rows", ROWS)
    cols     = dims.get("cols", COLS)
    lat_min  = bounds.get("lat_min", LAT_MIN)
    lat_max  = bounds.get("lat_max", LAT_MAX)
    lon_min  = bounds.get("lon_min", LON_MIN)
    lon_max  = bounds.get("lon_max", LON_MAX)

    cell_size_ft      = phys.get("cell_size_ft",       DEFAULT_CELL_SIZE_FT)
    time_step_min     = phys.get("time_step_min",      DEFAULT_TIME_STEP_MIN)
    burn_duration     = phys.get("burn_duration_ticks", DEFAULT_BURN_DURATION)

    print(f"Grid: {rows} rows x {cols} cols")
    print(f"Bounds: lat [{lat_min}, {lat_max}]  lon [{lon_min}, {lon_max}]")
    print(f"Physics: cell_size_ft={cell_size_ft}, time_step_min={time_step_min}, "
          f"burn_duration_ticks={burn_duration}")

    # ------------------------------------------------------------------
    # Parse cells
    # Key format: "row,col,layer"
    # ------------------------------------------------------------------
    cells = scenario.get("cells", {})
    print(f"Found {len(cells)} cells in JSON ...")

    out_rows = []
    skipped  = 0

    for key, val in cells.items():
        parts = key.split(",")
        if len(parts) != 3:
            skipped += 1
            continue

        try:
            row   = int(parts[0])
            col   = int(parts[1])
            layer = int(parts[2])
        except ValueError:
            skipped += 1
            continue

        out_rows.append({
            "col":                  col,
            "row":                  row,
            "layer":                layer,
            "cell_key":             key,
            "terrain":              val.get("terrain", ""),
            "vegetation":           val.get("vegetation", ""),
            "fuel_moisture":        val.get("fuel_moisture", ""),
            "slope":                val.get("slope", ""),
            "cell_size_ft":         int(cell_size_ft),
            "time_step_min":        time_step_min,
            "burn_duration_ticks":  burn_duration,
            "lat":                  cell_lat(row, rows, lat_max, lat_min),
            "lon":                  cell_lon(col, cols, lon_min, lon_max),
        })

    if skipped:
        print(f"Warning: skipped {skipped} malformed keys")

    # Sort by row then col for readability
    out_rows.sort(key=lambda r: (r["row"], r["col"]))

    # ------------------------------------------------------------------
    # Write CSV
    # ------------------------------------------------------------------
    fieldnames = [
        "col", "row", "layer", "cell_key",
        "terrain", "vegetation", "fuel_moisture", "slope",
        "cell_size_ft", "time_step_min", "burn_duration_ticks",
        "lat", "lon",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Written {len(out_rows)} rows to {output_path}")

    # ------------------------------------------------------------------
    # Quick summary
    # ------------------------------------------------------------------
    from collections import Counter
    terrain_counts = Counter(r["terrain"] for r in out_rows)
    print("\nTerrain breakdown:")
    for terrain, count in sorted(terrain_counts.items(), key=lambda x: -x[1]):
        print(f"  {count:5d}  {terrain}")

    # Verify corners
    corner_keys = {"0,0,0", f"0,{cols-1},0", f"{rows-1},0,0", f"{rows-1},{cols-1},0"}
    corner_rows = {r["cell_key"]: r for r in out_rows if r["cell_key"] in corner_keys}
    print("\nCorner check:")
    for k in sorted(corner_keys):
        if k in corner_rows:
            r = corner_rows[k]
            print(f"  {k:12s}  lat={r['lat']:10.6f}  lon={r['lon']:11.6f}  {r['terrain']}")
        else:
            print(f"  {k:12s}  (not in data)")


if __name__ == "__main__":
    main()
