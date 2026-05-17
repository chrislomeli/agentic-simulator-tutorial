"""
domains.wildfire.world_builder.cli.fetch_raws_stations

Fetch the active RAWS station list and latest readings for a region's
bounding box from the Synoptic Data API.

Writes a JSON snapshot to:
    world_builder/data/snapshots/raws_{region}.json

This is build-time tooling. The runtime simulator never calls this script —
it consumes the curated station list in world_builder/data/regions/*.json.
Run when you want to verify the live station list still matches the curated
list, or when you want fresh weather readings for a fixture.

Authentication
──────────────
Set SYNOPTIC_TOKEN in your environment. The script fails fast if it is
missing — never hardcode the token in source. Get one at
https://synopticdata.com.

    export SYNOPTIC_TOKEN=...
    fetch-raws-stations --region lpnf-south
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from domains.wildfire.world_builder.regions import get_region

API_BASE = "https://api.synopticdata.com/v2"
_SNAPSHOT_DIR = Path(__file__).parent.parent / "data" / "snapshots"


def _require_token() -> str:
    token = os.environ.get("SYNOPTIC_TOKEN")
    if not token:
        sys.stderr.write(
            "ERROR: SYNOPTIC_TOKEN env var is not set.\n"
            "Get a token at https://synopticdata.com and run:\n"
            "    export SYNOPTIC_TOKEN=...\n"
        )
        sys.exit(1)
    return token


def _get(endpoint: str, params: dict) -> dict:
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def find_raws_stations(token: str, bbox: str) -> list[dict]:
    data = _get(
        "stations/metadata",
        {
            "token": token,
            "bbox": bbox,
            "network": "2",  # RAWS
            "status": "active",
            "output": "json",
        },
    )
    print(f"Response: {data['SUMMARY']['RESPONSE_MESSAGE']}")
    stations = data.get("STATION", [])
    print(f"Found {len(stations)} active RAWS stations\n")
    for s in stations:
        print(f"  {s['STID']:12} {s['NAME']:35} lat={s['LATITUDE']}  lon={s['LONGITUDE']}")
    return stations


def get_latest_readings(token: str, stations: list[dict]) -> list[dict]:
    if not stations:
        return []
    ids = [s["STID"] for s in stations]
    data = _get(
        "stations/latest",
        {
            "token": token,
            "stid": ",".join(ids),
            "vars": "air_temp,relative_humidity,wind_speed,wind_direction",
            "units": "metric",
            "output": "json",
        },
    )
    return data.get("STATION", [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch live RAWS stations for a region.")
    parser.add_argument("--region", required=True, help="Region name, e.g. lpnf-south")
    args = parser.parse_args()

    region = get_region(args.region)
    bounds = region.bounds
    bbox = f"{bounds['lon_min']},{bounds['lat_min']},{bounds['lon_max']},{bounds['lat_max']}"

    output_path = _SNAPSHOT_DIR / f"raws_{region.name}.json"

    token = _require_token()
    stations = find_raws_stations(token, bbox)
    readings = get_latest_readings(token, stations)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "region": region.name,
                "bbox": bbox,
                "stations": stations,
                "latest": readings,
            },
            indent=2,
        )
    )
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
