#!/usr/bin/env python3
import sys
import argparse
import pandas as pd

# --- S3 Support
import boto3
from io import StringIO

def smart_read_csv(path, **kwargs):
    """Read CSV from S3 or local path transparently."""
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return pd.read_csv(StringIO(obj["Body"].read().decode()), **kwargs)
    else:
        return pd.read_csv(path, **kwargs)

def smart_to_csv(df, path, **kwargs):
    """Write CSV to S3 or local path transparently."""
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
# ---

VENUE_TO_PARK_ID = {
    "Coors Field":                  "col",
    "Fenway Park":                  "bos",
    "Great American Ball Park":     "cin",
    "Chase Field":                  "ari",
    "Target Field":                 "min",
    "LoanDepot Park":               "mia",
    "Kauffman Stadium":             "kc",
    "Oriole Park at Camden Yards":  "bal",
    "Nationals Park":               "was",
    "Dodger Stadium":               "lad",
    "Minute Maid Park":             "hou",
    "Yankee Stadium":               "nyy",
    "Truist Park":                  "atl",
    "Rogers Centre":                "tor",
    "PNC Park":                     "pit",
    "Citizens Bank Park":           "phi",
    "Busch Stadium":                "stl",
    "T-Mobile Park":                "sea",
    "Comerica Park":                "det",
    "Progressive Field":            "cle",
    "George M. Steinbrenner Field": "tb",
    "Wrigley Field":                "chc",
    "Oakland Coliseum":             "oak",
    "Angel Stadium":                "ana",
    "Petco Park":                   "sd",
    "American Family Field":        "mil",
    "Globe Life Field":             "tex",
    "Citi Field":                   "nym",
    "Tropicana Field":              "tb",
    # … add any other parks you see …
}

def normalize_park_factors(raw_csv: str, out_csv: str, season_year: int):
    df = smart_read_csv(raw_csv)

    if {"park_id", "year", "hr_factor"}.issubset(df.columns):
        print("📦 Input already normalized — copying through")
        smart_to_csv(df[["park_id", "year", "hr_factor"]], out_csv)
        return df

    if not {"Venue", "Park Factor"}.issubset(df.columns):
        sys.exit("Error: need raw Savant columns 'Venue' & 'Park Factor'")

    df["park_id"] = df["Venue"].map(VENUE_TO_PARK_ID)
    df["year"]    = season_year
    df = df.rename(columns={"Park Factor": "hr_factor"})
    out = df[["park_id", "year", "hr_factor"]].dropna(subset=["park_id"])
    smart_to_csv(out, out_csv)
    return out

def normalize_weather(raw_csv: str, out_csv: str):
    df = smart_read_csv(raw_csv, parse_dates=["date"])
    if not {"park", "date", "tavg", "wspd"}.issubset(df.columns):
        sys.exit("Error: weather‐raw must have either {park_id,date,tavg,wspd} or {park,date,tavg,wspd}")

    df["park_id"] = df["park"].map(VENUE_TO_PARK_ID)
    df = df.rename(columns={
        "tavg": "temp",
        "wspd": "wind_to_out"
    })
    df["wind_speed"] = df["wind_to_out"]

    out = (
        df[["park_id", "date", "temp", "wind_to_out", "wind_speed"]]
        .rename(columns={"date": "game_date"})
        .dropna(subset=["park_id"])
    )
    smart_to_csv(out, out_csv, date_format="%Y-%m-%d")
    return out

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Normalize raw park-factor & weather CSVs"
    )
    p.add_argument("--park_raw",    required=True,
                   help="Raw park-factor CSV (may be s3://...)")
    p.add_argument("--park_out",    required=True,
                   help="Output normalized park_factors.csv (may be s3://...)")
    p.add_argument("--weather_raw", required=True,
                   help="Raw weather CSV (may be s3://...)")
    p.add_argument("--weather_out", required=True,
                   help="Output normalized weather CSV (may be s3://...)")
    p.add_argument("--year", type=int, required=True,
                   help="Season year (e.g. 2025)")
    args = p.parse_args()

    normalize_park_factors(
        args.park_raw,
        args.park_out,
        args.year
    )
    normalize_weather(
        args.weather_raw,
        args.weather_out
    )
