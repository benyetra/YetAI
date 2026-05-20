#!/usr/bin/env python3
import pandas as pd

# Static list of MLB parks → your 3-letter codes + lat/lon
# Coordinates sourced from Google Maps / public domain.
PARK_COORDS = {
    "ana": (33.8003, -117.8827),  # Angel Stadium
    "ari": (33.4458, -112.0665),  # Chase Field
    "atl": (33.8908, -84.4677),  # Truist Park
    "bal": (39.2839, -76.6214),  # Camden Yards
    "bos": (42.3467, -71.0972),  # Fenway Park
    "chc": (41.9484, -87.6553),  # Wrigley Field
    "cws": (41.8309, -87.6339),  # Guaranteed Rate
    "cin": (39.0974, -84.5060),  # Great American
    "cle": (41.4950, -81.6850),  # Progressive Field
    "col": (39.7559, -104.9942),  # Coors Field
    "det": (42.3399, -83.0485),  # Comerica Park
    "hou": (29.7573, -95.3553),  # Minute Maid Park
    "kc": (39.0516, -94.4805),  # Kauffman Stadium
    "lac": (34.0736, -118.2395),  # (no team)
    "lad": (34.0738, -118.2390),  # Dodger Stadium
    "mia": (25.7781, -80.2195),  # loanDepot Park
    "mil": (43.0285, -87.9712),  # American Family Field
    "min": (44.9817, -93.2778),  # Target Field
    "nym": (40.7571, -73.8458),  # Citi Field
    "nyy": (40.8296, -73.9262),  # Yankee Stadium
    "oak": (37.7516, -122.2005),  # RingCentral Coliseum
    "phi": (39.9061, -75.1665),  # Citizens Bank Park
    "pit": (40.4469, -80.0051),  # PNC Park
    "sd": (32.7076, -117.1570),  # Petco Park
    "sea": (47.5914, -122.3325),  # T-Mobile Park
    "sfg": (37.7786, -122.3893),  # Oracle Park
    "stl": (38.6224, -90.1928),  # Busch Stadium
    "tb": (27.7682, -82.6534),  # Tropicana Field
    "tex": (32.7516, -97.0824),  # Globe Life Field
    "tor": (43.6414, -79.3893),  # Rogers Centre
    "was": (38.8721, -77.0074),  # Nationals Park
}


def main(output_path):
    df = pd.DataFrame(
        [
            {"park_id": pid, "lat": lat, "lon": lon}
            for pid, (lat, lon) in PARK_COORDS.items()
        ]
    )
    df.to_csv(output_path, index=False)
    print(f"✅ Wrote {len(df)} rows to {output_path}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Generate park_coords.csv from a static list"
    )
    p.add_argument("--output", required=True, help="Where to write park_coords.csv")
    args = p.parse_args()
    main(args.output)
