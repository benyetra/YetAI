#!/usr/bin/env python3
import argparse
import os
import sys
import pandas as pd
import numpy as np
import unicodedata

# Optional: S3 support
try:
    import boto3
    from io import BytesIO, StringIO
except ImportError:
    boto3 = None

def strip_accents(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ASCII", "ignore")
        .decode("ASCII", "ignore")
    )

def normalize_player_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if "," in s:
        last, first = s.split(",", 1)
        s = f"{first.strip()} {last.strip()}"
    return strip_accents(s).lower()

def s3_exists(bucket, key):
    try:
        boto3.client("s3").head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def read_csv_anywhere(path, **kwargs):
    if path.startswith("s3://"):
        if boto3 is None:
            raise ImportError("boto3 required for S3 support")
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return pd.read_csv(BytesIO(obj["Body"].read()), **kwargs)
    else:
        return pd.read_csv(path, **kwargs)

def write_csv_anywhere(df, path, **kwargs):
    if path.startswith("s3://"):
        if boto3 is None:
            raise ImportError("boto3 required for S3 support")
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, **kwargs)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        print(f"✅ Wrote {len(df)} total rows → {path}")
    else:
        df.to_csv(path, **kwargs)
        print(f"✅ Wrote {len(df)} total rows → {path}")

def compute_power_profile(statcast_csv: str, slugging_csv: str) -> pd.DataFrame:
    stats_df = read_csv_anywhere(slugging_csv)
    if not {"player_id", "SLG"}.issubset(stats_df.columns):
        sys.exit(f"Error: slugging CSV '{slugging_csv}' must have 'player_id' & 'SLG'")
    slug = stats_df.set_index("player_id")[["SLG"]]

    stat = read_csv_anywhere(statcast_csv, low_memory=False, parse_dates=["game_date"])
    stat = stat.dropna(subset=["launch_speed", "bb_type"])
    stat["batter"] = stat["batter"].astype(int)

    counts = stat.groupby("batter").size().rename("TotalBB")
    keep = counts[counts >= 50].index
    bb = stat[stat["batter"].isin(keep)]

    aev = bb.groupby("batter")["launch_speed"].mean().rename("AEV")
    hard = bb[bb["launch_speed"] >= 95].groupby("batter").size().rename("HardHits")
    hrate = (hard / counts.loc[keep]).rename("HardHitRate")

    df = pd.concat([aev, hrate], axis=1).join(slug, how="inner").dropna(subset=["SLG"])

    for col, weight in [("AEV", 0.4), ("HardHitRate", 0.3), ("SLG", 0.3)]:
        μ = df[col].mean()
        σ = df[col].std(ddof=0)
        df[f"Z_{col}"] = ((df[col] - μ) / σ) if σ else 0.0
    df["PowerScore"] = (
        0.4 * df["Z_AEV"] +
        0.3 * df["Z_HardHitRate"] +
        0.3 * df["Z_SLG"]
    )

    idx_name = df.index.name or "index"
    df = df.reset_index().rename(columns={idx_name: "batter_id"})
    df["batter_id"] = df["batter_id"].astype(int)
    return df[["batter_id", "AEV", "HardHitRate", "SLG", "PowerScore"]]

def file_exists_anywhere(path):
    if path.startswith("s3://"):
        if boto3 is None:
            raise ImportError("boto3 required for S3 support")
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        return s3_exists(bucket, key)
    else:
        return os.path.exists(path)

def main():
    p = argparse.ArgumentParser(description="Compute multi-year PowerScore (S3/local support)")
    p.add_argument("--start", type=int, required=True, help="first season")
    p.add_argument("--end", type=int, required=True, help="last season")
    p.add_argument("--statcast_dir", required=True, help="directory with statcast_bb_{year}.csv files (local or s3)")
    p.add_argument("--slugging_dir", required=True, help="directory with slugging_{year}.csv files (local or s3)")
    p.add_argument("--output", required=True, help="where to write the combined power_scores_all.csv (local or s3)")
    args = p.parse_args()

    all_dfs = []
    for year in range(args.start, args.end + 1):
        sc = os.path.join(args.statcast_dir, f"statcast_bb_{year}.csv") \
            if not args.statcast_dir.startswith("s3://") else f"{args.statcast_dir.rstrip('/')}/statcast_bb_{year}.csv"
        sl = os.path.join(args.slugging_dir, f"slugging_{year}.csv") \
            if not args.slugging_dir.startswith("s3://") else f"{args.slugging_dir.rstrip('/')}/slugging_{year}.csv"

        print(f"→ Computing PowerScore for {year}…")
        if not file_exists_anywhere(sc):
            print(f"   ⚠️  missing statcast file {sc}, skipping", file=sys.stderr)
            continue
        if not file_exists_anywhere(sl):
            print(f"   ⚠️  missing slugging file {sl}, skipping", file=sys.stderr)
            continue

        year_df = compute_power_profile(sc, sl)
        year_df["year"] = year
        all_dfs.append(year_df)

    if not all_dfs:
        sys.exit("Error: no years successfully processed.")
    result = pd.concat(all_dfs, ignore_index=True)
    write_csv_anywhere(result, args.output, index=False)

if __name__ == "__main__":
    main()
