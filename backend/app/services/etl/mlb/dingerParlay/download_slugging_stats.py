#!/usr/bin/env python3
import os
import sys
import argparse
import pandas as pd
from pybaseball import batting_stats_range
import statsapi

# ---- S3 SUPPORT ----
import boto3
from io import StringIO

def write_csv(df, path):
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        print(f"✅ Wrote {len(df)} rows → s3://{bucket}/{key}")
    else:
        df.to_csv(path, index=False)
        print(f"✅ Wrote {len(df)} rows → {path}")

def strip_accents(text: str) -> str:
    import unicodedata
    if not isinstance(text, str):
        return ""
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ASCII", "ignore")
        .decode("ASCII", "ignore")
    )

def download_slugging_stats_for_year(year: int, out_csv: str):
    """
    Fetch batting totals for one season, compute SLG, and attach MLBAM ID.
    Writes slugging_<year>.csv with columns:
      player_name, AB, H, 2B, 3B, HR, SLG, player_id
    """
    start_dt = f"{year}-01-01"
    end_dt   = f"{year}-12-31"
    print(f"📥 [{year}] Fetching batting stats {start_dt} → {end_dt} …")
    df = batting_stats_range(start_dt, end_dt)

    # keep only MLB
    if "Level" in df.columns:
        df = df[df["Level"] == "MLB"]

    # compute SLG
    df["Singles"]    = df["H"] - df["2B"] - df["3B"] - df["HR"]
    df["TotalBases"] = (
        df["Singles"] * 1 +
        df["2B"]      * 2 +
        df["3B"]      * 3 +
        df["HR"]      * 4
    )
    df["SLG"] = df["TotalBases"] / df["AB"].replace({0: pd.NA})

    # prepare output
    out = df.rename(columns={"Name":"player_name"})[
        ["player_name","AB","H","2B","3B","HR","SLG"]
    ].copy()

    # try to find existing ID column
    candidates = [c for c in df.columns
                  if c.lower() in ("key_mlbam_id","playerid","player_id","id","mlbamid")]
    if candidates:
        id_col = candidates[0]
        print(f"🔗 [{year}] using built-in ID column '{id_col}'")
        out["player_id"] = df[id_col]
    else:
        # fallback: only for players with AB >= 100
        print(f"⚠️  [{year}] no built-in ID; resolving via statsapi for AB>=100 …")
        mask = out["AB"] >= 100
        names = out.loc[mask, "player_name"].unique()
        lookup = {}
        for name in names:
            try:
                rec = statsapi.lookup_player(name)
                lookup[name] = rec[0]["id"] if rec else pd.NA
            except:
                lookup[name] = pd.NA
        out["player_id"] = out["player_name"].map(lookup)

    # write (local or S3)
    write_csv(out, out_csv)

def main():
    p = argparse.ArgumentParser(
        description="Download year-by-year slugging CSVs with MLBAM IDs"
    )
    p.add_argument("--start_season", type=int, required=True,
                   help="First season (e.g. 2013)")
    p.add_argument("--end_season",   type=int, required=True,
                   help="Last season  (e.g. 2025)")
    p.add_argument("--out_dir",      required=True,
                   help="Directory or s3://bucket/prefix/ to write slugging_<year>.csv")
    args = p.parse_args()

    # Is S3?
    is_s3 = args.out_dir.startswith("s3://")
    if not is_s3:
        os.makedirs(args.out_dir, exist_ok=True)

    for y in range(args.start_season, args.end_season + 1):
        if is_s3:
            # handle trailing / for S3
            prefix = args.out_dir.rstrip("/") + "/"
            out_csv = f"{prefix}slugging_{y}.csv"
        else:
            out_csv = os.path.join(args.out_dir, f"slugging_{y}.csv")
        download_slugging_stats_for_year(y, out_csv)

if __name__ == "__main__":
    main()
