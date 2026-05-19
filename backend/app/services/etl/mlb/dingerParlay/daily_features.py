#!/usr/bin/env python3
import argparse
import logging
import sys
from datetime import datetime

import pandas as pd
import boto3
from io import BytesIO, StringIO

def read_s3_csv(bucket, key, **kwargs):
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    raw = obj["Body"].read()
    try:
        return pd.read_csv(StringIO(raw.decode("utf-8")), **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(BytesIO(raw), **kwargs)

def smart_read_csv(path, **kwargs):
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key    = "/".join(path.split("/")[3:])
        return read_s3_csv(bucket, key, **kwargs)
    return pd.read_csv(path, **kwargs)

def write_s3_csv(df, path):
    csv = df.to_csv(index=False)
    bucket, key = path.split("/")[2], "/".join(path.split("/")[3:])
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv)

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser(
        description="Build daily feature file for HR model"
    )
    p.add_argument("--lineup",       required=True, help="today_lineup.csv")
    p.add_argument("--power-scores", required=True, help="power_scores.csv")
    p.add_argument("--pitcher-stats",required=True, help="pitcher_stats.csv")
    p.add_argument("--park-factors", required=True, help="park_factors.csv")
    p.add_argument("--weather",      required=True, help="weather_normalized.csv")
    p.add_argument("--output",       required=True, help="where to save daily_features.csv")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    # 1) load and dedupe lineup, rename hand → starter_hand
    log("Loading today’s lineup")
    df = smart_read_csv(args.lineup, parse_dates=["game_date"])
    if "pitcher_hand" not in df.columns:
        sys.exit("Error: your lineup.csv must include a 'pitcher_hand' column")
    df = df.rename(columns={"pitcher_hand":"starter_hand"})
    df = df.drop_duplicates(subset=["batter_id","pitcher_id","park_id"])
    df["year"] = df["game_date"].dt.year

    # 2) merge PowerScore
    log("Merging PowerScore")
    ps = smart_read_csv(args.power_scores)
    df = df.merge(
        ps[["player_id","PowerScore"]],
        left_on="batter_id", right_on="player_id", how="left"
    ).drop(columns="player_id")
    df = df.dropna(subset=["PowerScore"])

    # 3) merge pitcher HR9, K9
    log("Merging PitcherStats")
    pstats = smart_read_csv(args.pitcher_stats)
    df = df.merge(
        pstats[["pitcher_id","HR9","K9"]],
        on="pitcher_id", how="left"
    )
    df = df.dropna(subset=["HR9","K9"])

    # 4) merge park factors
    log("Merging ParkFactors")
    parks = smart_read_csv(args.park_factors)
    df = df.merge(
        parks[["park_id","year","hr_factor"]],
        on=["park_id","year"], how="left"
    )
    df["hr_factor"] = df["hr_factor"].fillna(1.0)

    # 5) merge weather
    log("Merging Weather")
    w = smart_read_csv(args.weather, parse_dates=["game_date"])
    if "wind_to_out" in w.columns and "wind_speed" not in w.columns:
        w["wind_speed"] = w["wind_to_out"]
    w = w.drop_duplicates(subset=["park_id","game_date"])
    df = df.merge(
        w[["park_id","game_date","temp","wind_speed"]],
        on=["park_id","game_date"], how="left"
    )
    df["temp"]       = df["temp"].fillna(w["temp"].median())
    df["wind_speed"] = df["wind_speed"].fillna(0.0)

    # 6) compute platoon
    log("Computing platoon")
    df["platoon"] = (
        df["batter_hand"].str.upper() != df["starter_hand"].str.upper()
    ).astype(int)

    # 7) select only the 7 model features + IDs
    feats = ["PowerScore","HR9","K9","hr_factor","temp","wind_speed","platoon"]
    missing = set(feats) - set(df.columns)
    if missing:
        logging.error(f"Missing columns for model: {missing}")
        sys.exit(1)

    out = df[["batter_id","pitcher_id","park_id","game_date"] + feats]

    # 8) write back out
    log(f"Writing {len(out)} rows to {args.output}")
    if args.output.startswith("s3://"):
        write_s3_csv(out, args.output)
    else:
        out.to_csv(args.output, index=False)

    log("Done.")

if __name__ == "__main__":
    main()
