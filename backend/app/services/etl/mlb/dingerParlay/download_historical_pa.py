#!/usr/bin/env python3
import argparse
import sys
import os
import pandas as pd
from pybaseball import statcast
from datetime import datetime

# S3 helper
import boto3
from io import StringIO

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

def smart_dir_write(df, base_path, filename):
    """Write to either local dir or S3 'directory'."""
    if base_path.startswith("s3://"):
        # remove trailing slash if present
        base_path = base_path.rstrip("/")
        # Compose s3://bucket/dir/filename
        path = f"{base_path}/{filename}"
        smart_to_csv(df, path)
    else:
        os.makedirs(base_path, exist_ok=True)
        path = os.path.join(base_path, filename)
        df.to_csv(path, index=False)
        print(f"  • Wrote {len(df)} rows → {path}")

def download_historical_pa(start_year: int, end_year: int, combined_csv: str, out_dir: str):
    all_dfs = []
    for year in range(start_year, end_year + 1):
        season_start = f"{year}-03-01"
        season_end   = f"{year}-10-31"
        print(f"→ Fetching {season_start} → {season_end} …", end=" ", flush=True)
        try:
            df_year = statcast(season_start, season_end)
        except Exception as e:
            print(f"❌ failed: {e}")
            sys.exit(1)

        if df_year.empty:
            print("⚠️  no rows returned")
        else:
            print(f"✓ {len(df_year)} rows")
            all_dfs.append(df_year)

    if not all_dfs:
        print("Error: No data fetched for any year. Exiting.")
        sys.exit(1)

    # Concatenate all years
    print("Concatenating all yearly DataFrames …")
    full_df = pd.concat(all_dfs, ignore_index=True)

    # Ensure 'game_date' is datetime
    if "game_date" not in full_df.columns:
        print("Error: downloaded Statcast data contains no 'game_date'.", file=sys.stderr)
        sys.exit(1)
    full_df["game_date"] = pd.to_datetime(full_df["game_date"], errors="coerce")

    # 1) Write combined historical_pa.csv
    print(f"Writing combined data ({len(full_df)} rows) → {combined_csv}")
    smart_to_csv(full_df, combined_csv)

    # 2) Split out per‐year files
    for year, df_yr in full_df.groupby(full_df["game_date"].dt.year):
        fn = f"statcast_bb_{year}.csv"
        smart_dir_write(df_yr, out_dir, fn)

    print("Done.")

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Download Statcast PA by season, plus split per-year."
    )
    p.add_argument("--start-year", type=int, required=True,
                   help="First season (e.g. 2013)")
    p.add_argument("--end-year",   type=int, required=True,
                   help="Last season (e.g. 2025)")
    p.add_argument("--combined",   required=True,
                   help="Path to write full historical_pa.csv (local or s3://...)")
    p.add_argument("--out-dir",    required=True,
                   help="Directory to write per-year statcast_bb_{year}.csv files (local or s3://...)")
    args = p.parse_args()

    if args.start_year > args.end_year:
        print("Error: --start-year must be ≤ --end-year.", file=sys.stderr)
        sys.exit(1)

    download_historical_pa(
        args.start_year,
        args.end_year,
        args.combined,
        args.out_dir
    )
