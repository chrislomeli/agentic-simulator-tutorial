import csv
import ast

INPUT_FILE = "../raw/sensors.jsonl"
OUTPUT_FILE = "../raw/sensor_overlay.csv"

rows = []

with open(INPUT_FILE, "r") as infile:

    for line in infile:

        line = line.strip()

        if not line:
            continue

        row = ast.literal_eval(line)

        rows.append(row)

fieldnames = [
    "grid_row",
    "grid_column",
    "elevation",

    "sensor_id",
    "sensor_name",
    "sensor_type",

    "cluster_name",
    "noise_std"
]

with open(OUTPUT_FILE, "w", newline="") as outfile:

    writer = csv.DictWriter(
        outfile,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")