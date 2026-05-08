"""
domains.wildfire.world_builder.cli.build_fuel_grid

Build a vendored fuel-grid JSON from LANDFIRE GeoTIFF rasters.

Reads three LANDFIRE rasters (FBFM40 fuel models, EVT vegetation, CC
canopy cover), clips to the region's bounding box, aggregates into
30x30 pixel blocks (~900 m per cell), and writes:

    scenario_data/landfire/{region}/fuel_grid.json

The runtime simulator never reads the source TIFFs — it reads the
vendored JSON. Regenerate when source data changes or the bbox is retuned.

Requirements
────────────
The GIS stack (rasterio, geopandas, pyproj, shapely) is not a runtime
dependency. Install via the [gis] extras group:

    uv pip install -e ".[gis]"

LANDFIRE source data
────────────────────
Download three CONUS rasters from https://landfire.gov (LF 2025 set):

  * LF2025_FBFM40_CONUS.tif  (Scott & Burgan 40 fuel models)
  * LF2025_FVT_CONUS.tif     (Existing Vegetation Type)
  * LF2025_CC_CONUS.tif      (Canopy Cover %)

Set LANDFIRE_SOURCE_DIR to the directory containing the TIFFs.

Usage
─────
    build-fuel-grid --region lpnf-south
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.mask import mask
from rasterio.transform import xy
from shapely.geometry import box

from domains.wildfire.world_builder.regions import RegionProfile, get_region


def _require_landfire_source_dir() -> Path:
    val = os.environ.get(key="LANDFIRE_SOURCE_DIR", default="./lpnf")
    if not val:
        raise OSError(
            "LANDFIRE_SOURCE_DIR is not set.\n"
            "Point it at the directory containing the LANDFIRE GeoTIFFs:\n"
            "    export LANDFIRE_SOURCE_DIR=/path/to/tifs\n"
            "Download from https://landfire.gov (LF 2025 CONUS set)."
        )
    return Path(val)


# 30 raster pixels per output cell → ~900 m × 900 m per cell
CELL_SIZE = 30


class RasterLayer:
    """Clipped raster with safe pixel→latlon and block-aggregation helpers."""

    def __init__(self, path: Path, aoi_gdf: gpd.GeoDataFrame) -> None:
        with rasterio.open(path) as src:
            self.crs = src.crs
            self.nodata = src.nodata
            aoi_proj = aoi_gdf.to_crs(src.crs)
            data, self.transform = mask(src, aoi_proj.geometry, crop=True)
            self.data = data[0]
        self.to_wgs84 = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)

    def pixel_to_latlon(self, row: int, col: int) -> tuple[float, float]:
        x, y = xy(self.transform, row, col)
        lon, lat = self.to_wgs84.transform(x, y)
        return float(lat), float(lon)

    def block(self, r: int, c: int, size: int) -> np.ndarray:
        return self.data[r : r + size, c : c + size]

    def safe_mode(self, arr: np.ndarray) -> int | None:
        flat = arr.flatten()
        if self.nodata is not None:
            flat = flat[flat != self.nodata]
        flat = flat[flat > 0]
        return None if len(flat) == 0 else int(np.bincount(flat.astype(int)).argmax())

    def safe_mean(self, arr: np.ndarray) -> float | None:
        flat = arr.flatten()
        if self.nodata is not None:
            flat = flat[flat != self.nodata]
        flat = flat[flat >= 0]
        return None if len(flat) == 0 else float(np.mean(flat))


def build_fuel_grid(region: RegionProfile) -> None:
    source_dir = _require_landfire_source_dir()
    fbfm_path = source_dir / "LF2025_FBFM40_CONUS.tif"
    evt_path = source_dir / "LF2025_FVT_CONUS.tif"
    cc_path = source_dir / "LF2025_CC_CONUS.tif"

    bounds = region.bounds
    output_path = region.fuel_grid_path
    bbox_path = output_path.with_name("fuel_grid_bbox.json")

    for p in (fbfm_path, evt_path, cc_path):
        if not p.exists():
            raise FileNotFoundError(
                f"LANDFIRE raster not found: {p}\n"
                f"Download from https://landfire.gov (LF 2025 CONUS set)."
            )

    aoi = gpd.GeoDataFrame(
        geometry=[box(bounds["lon_min"], bounds["lat_min"], bounds["lon_max"], bounds["lat_max"])],
        crs="EPSG:4326",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bbox_path.write_text(
        json.dumps(
            {
                "region": region.name,
                "min_lon": bounds["lon_min"],
                "min_lat": bounds["lat_min"],
                "max_lon": bounds["lon_max"],
                "max_lat": bounds["lat_max"],
            },
            indent=2,
        )
    )
    print(f"Wrote bbox to {bbox_path}")

    print("Loading rasters...")
    fbfm = RasterLayer(fbfm_path, aoi)
    evt = RasterLayer(evt_path, aoi)
    cc = RasterLayer(cc_path, aoi)
    print(f"Done. FBFM shape: {fbfm.data.shape}")

    print("Building grid...")
    rows, cols = fbfm.data.shape
    results: list[dict] = []
    cell_id = 0

    for r in range(0, rows, CELL_SIZE):
        for c in range(0, cols, CELL_SIZE):
            f_block = fbfm.block(r, c, CELL_SIZE)
            if f_block.shape != (CELL_SIZE, CELL_SIZE):
                continue
            fuel = fbfm.safe_mode(f_block)
            if fuel is None:
                continue
            veg = evt.safe_mode(evt.block(r, c, CELL_SIZE))
            can = cc.safe_mean(cc.block(r, c, CELL_SIZE))
            lat, lon = fbfm.pixel_to_latlon(r, c)
            results.append(
                {
                    "cell_id": cell_id,
                    "lat": lat,
                    "lon": lon,
                    "fuel_model_code": fuel,
                    "vegetation_type_code": veg,
                    "canopy_cover": can,
                }
            )
            cell_id += 1
            if cell_id % 5000 == 0:
                print(f"  {cell_id} cells...")

    print(f"Total cells: {len(results)}")
    print(f"Writing {output_path}...")
    output_path.write_text(json.dumps(results, indent=2))
    print("Done.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build LANDFIRE fuel grid for a region.")
    parser.add_argument("--region", required=True, help="Region name, e.g. lpnf-south")
    args = parser.parse_args()
    build_fuel_grid(get_region(args.region))


if __name__ == "__main__":
    main()
