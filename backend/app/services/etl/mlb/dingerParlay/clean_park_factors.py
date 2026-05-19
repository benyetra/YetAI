#!/usr/bin/env python3
import argparse
import sys
import pandas as pd

# ---- S3 Support ----
import boto3
from io import StringIO

def smart_read_csv(path, **kwargs):
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return pd.read_csv(StringIO(obj["Body"].read().decode()), **kwargs)
    else:
        return pd.read_csv(path, **kwargs)

def smart_to_csv(df, path, **kwargs):
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, **kwargs)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        print(f"✅ Wrote {len(df)} rows → s3://{bucket}/{key}")
    else:
        df.to_csv(path, index=False, **kwargs)
        print(f"✅ Wrote {len(df)} rows → {path}")

# ───────────────────────────────────────────────────────────────────────────
TEAM_TO_ABBR = {
    "D-backs":      "ari",  "Diamondbacks": "ari",
    "Braves":       "atl",
    "Orioles":      "bal",
    "Red Sox":      "bos",
    "Cubs":         "chc",
    "White Sox":    "cws",
    "Reds":         "cin",
    "Guardians":    "cle",
    "Rockies":      "col",
    "Tigers":       "det",
    "Astros":       "hou",
    "Royals":       "kc",
    "Angels":       "ana",
    "Dodgers":      "lad",
    "Marlins":      "mia",
    "Brewers":      "mil",
    "Twins":        "min",
    "Mets":         "nym",
    "Yankees":      "nyy",
    "Athletics":    "oak",
    "Phillies":     "phi",
    "Pirates":      "pit",
    "Padres":       "sd",
    "Giants":       "sf",
    "Mariners":     "sea",
    "Cardinals":    "stl",
    "Rays":         "tb",
    "Rangers":      "tex",
    "Blue Jays":    "tor",
    "Nationals":    "was",
}
# ───────────────────────────────────────────────────────────────────────────

def main(raw_csv: str, output_csv: str):
    """
    Reads your raw park_factor.csv (with a “Year” column) and emits:
      park_id,park,year,hr_factor
    """
    df = smart_read_csv(raw_csv)

    # check required columns
    for col in ("Team","Year","Park Factor"):
        if col not in df.columns:
            sys.exit(f"Error: '{col}' column not found in {raw_csv}")

    rows = []
    for idx, row in df.iterrows():
        team = str(row["Team"]).strip()
        if team not in TEAM_TO_ABBR:
            print(f"Warning: unrecognized team '{team}' (row {idx}); skipping", file=sys.stderr)
            continue

        park_id   = TEAM_TO_ABBR[team]
        year      = int(row["Year"])
        try:
            hr_factor = float(row["Park Factor"])
        except Exception:
            print(f"Warning: invalid Park Factor '{row['Park Factor']}' @ row {idx}; skipping", file=sys.stderr)
            continue

        rows.append({
            "park_id":   park_id,
            "park":      park_id,  # duplicates park_id so build_training_data can find either
            "year":      year,
            "hr_factor": hr_factor
        })

    if not rows:
        sys.exit("Error: no valid park-factor rows parsed!")

    out = pd.DataFrame(rows)
    out = out.drop_duplicates(subset=["park_id","year"])
    out = out[["park_id","park","year","hr_factor"]]
    smart_to_csv(out, output_csv)

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Convert raw park-factor CSV into (park_id,park,year,hr_factor)"
    )
    p.add_argument("--raw",    required=True, help="Raw CSV with columns Team,Year,Park Factor (local or s3://)")
    p.add_argument("--output", required=True, help="Where to write park_factors.csv (local or s3://)")
    args = p.parse_args()
    main(args.raw, args.output)
