#!/usr/bin/env python3
import argparse, sys
from datetime import datetime
import pandas as pd

# ---- S3 Support ----
import boto3
from io import StringIO


def smart_read_csv(path, **kwargs):
    """Read a CSV from S3 or local path transparently."""
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return pd.read_csv(StringIO(obj["Body"].read().decode()), **kwargs)
    else:
        return pd.read_csv(path, **kwargs)


def smart_to_csv(df, path, **kwargs):
    """Write a CSV to S3 or local path transparently."""
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, **kwargs)
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=csv_buffer.getvalue()
        )
        print(f"✅ Wrote {len(df)} rows → s3://{bucket}/{key}")
    else:
        df.to_csv(path, index=False, **kwargs)
        print(f"✅ Wrote {len(df)} rows → {path}")


# -------------------------------------------------------------------------


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def build_training_data(
    pa_csv: str,
    power_csv: str,
    pitcher_stats_csv: str,
    park_factors_csv: str,
    weather_csv: str,
    output_csv: str,
):
    # ── 1) LOAD PA & EXTRACT IDS/YEARS ───────────────────────────────────
    log("📥 Loading plate appearances…")
    pa = smart_read_csv(pa_csv, parse_dates=["game_date"], low_memory=False)

    # standardize batter_id/pitcher_id and year
    if "batter" in pa.columns and "batter_id" not in pa.columns:
        pa = pa.rename(columns={"batter": "batter_id"})
        pa["batter_id"] = pa["batter_id"].astype(int)
    if "pitcher" in pa.columns and "pitcher_id" not in pa.columns:
        pa = pa.rename(columns={"pitcher": "pitcher_id"})
        pa["pitcher_id"] = pa["pitcher_id"].astype(int)
    pa["year"] = pa["game_date"].dt.year

    # ── 2) MERGE MULTI-YEAR POWER SCORES ────────────────────────────────
    log("🔗 Loading & deduping PowerScore…")
    power = smart_read_csv(power_csv)
    need = {"batter_id", "year", "PowerScore"}
    if not need.issubset(power.columns):
        sys.exit(f"Error: power CSV must have columns {need}")
    dup = power.duplicated(subset=["batter_id", "year"]).sum()
    if dup:
        log(f"→ {dup} duplicate PowerScore rows; dropping duplicates")
        power = power.drop_duplicates(subset=["batter_id", "year"], keep="last")

    log("🔗 Merging PA ⇄ PowerScore…")
    df = pa.merge(
        power[["batter_id", "year", "PowerScore"]],
        on=["batter_id", "year"],
        how="left",
        validate="m:1",
    )
    miss = df["PowerScore"].isna().sum()
    if miss:
        log(f"→ {miss:,} missing PowerScore; imputing by season median")
        df["PowerScore"] = df.groupby("year")["PowerScore"].transform(
            lambda s: s.fillna(s.median())
        )

    # ── 3) MERGE MULTI-YEAR PITCHER STATS ──────────────────────────────
    log("🔗 Loading & deduping PitcherStats…")
    pstats = smart_read_csv(pitcher_stats_csv)
    need = {"pitcher_id", "year", "HR9", "K9", "pitcher_hand"}
    if not need.issubset(pstats.columns):
        sys.exit(f"Error: pitcher_stats CSV must have columns {need}")
    dup = pstats.duplicated(subset=["pitcher_id", "year"]).sum()
    if dup:
        log(f"→ {dup} duplicate pitcher_stats rows; dropping duplicates")
        pstats = pstats.drop_duplicates(subset=["pitcher_id", "year"], keep="last")

    log("🔗 Merging PA ⇄ PitcherStats…")
    df = df.merge(
        pstats[["pitcher_id", "year", "HR9", "K9", "pitcher_hand"]],
        on=["pitcher_id", "year"],
        how="left",
        validate="m:1",
    )
    for col in ("HR9", "K9"):
        miss = df[col].isna().sum()
        if miss:
            log(f"→ {miss:,} missing {col}; imputing by season median")
            df[col] = df.groupby("year")[col].transform(lambda s: s.fillna(s.median()))

    # ── 4) MERGE PARK FACTORS ──────────────────────────────────────────
    log("🔗 Loading & deduping ParkFactors…")
    parks = smart_read_csv(park_factors_csv)
    need = {"park_id", "year", "hr_factor"}
    if not need.issubset(parks.columns):
        sys.exit(f"Error: park_factors CSV must have columns {need}")
    dup = parks.duplicated(subset=["park_id", "year"]).sum()
    if dup:
        log(f"→ {dup} duplicate park_factor rows; dropping duplicates")
        parks = parks.drop_duplicates(subset=["park_id", "year"], keep="last")

    log("🔗 Merging park factors…")
    df["park_id"] = df["home_team"].str.lower()
    df = df.merge(
        parks[["park_id", "year", "hr_factor"]],
        on=["park_id", "year"],
        how="left",
        validate="m:1",
    )
    df["hr_factor"] = df["hr_factor"].fillna(1.0)

    # ── 5) MERGE WEATHER ───────────────────────────────────────────────
    log("🔗 Loading & deduping Weather…")
    weather = smart_read_csv(weather_csv, parse_dates=["date"])
    weather = weather.rename(
        columns={"date": "game_date", "tavg": "temp", "wspd": "wind_speed"}
    )
    need = {"park_id", "game_date", "temp", "wind_speed"}
    if not need.issubset(weather.columns):
        sys.exit(f"Error: weather CSV must have columns {need}")
    dup = weather.duplicated(subset=["park_id", "game_date"]).sum()
    if dup:
        log(f"→ {dup} duplicate weather rows; dropping duplicates")
        weather = weather.drop_duplicates(subset=["park_id", "game_date"], keep="last")

    log("🔗 Merging weather…")
    df = df.merge(
        weather[["park_id", "game_date", "temp", "wind_speed"]],
        on=["park_id", "game_date"],
        how="left",
        validate="m:1",
    )
    if df["temp"].isna().any():
        log("→ Some weather missing; imputing global median & zero wind")
        df["temp"] = df["temp"].fillna(df["temp"].median())
        df["wind_speed"] = df["wind_speed"].fillna(0.0)

    # ── 6) DERIVED FEATURES & TARGET ───────────────────────────────────
    log("⚙️ Computing platoon & is_HR…")
    df["platoon"] = (df["stand"] != df["p_throws"].str.upper()).astype(int)
    df["is_HR"] = (df["events"] == "home_run").astype(int)

    # ── 7) FINAL DROP (only on the true target) ────────────────────────
    before = len(df)
    df = df.dropna(subset=["is_HR"])
    after = len(df)
    log(f"→ Dropped {before-after:,} rows; {after:,} remain")

    # ── 8) WRITE OUT ───────────────────────────────────────────────────
    log(f"💾 Writing training data → {output_csv}")
    smart_to_csv(df, output_csv, date_format="%Y-%m-%d")
    log("✅ Done!")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Build ML-ready training data from PA + multi-year features"
    )
    p.add_argument("--pa", required=True, help="historical_pa.csv or s3://...")
    p.add_argument("--power", required=True, help="power_scores_all.csv or s3://...")
    p.add_argument(
        "--pitcher_stats", required=True, help="pitcher_stats_all.csv or s3://..."
    )
    p.add_argument("--park_factors", required=True, help="park_factors.csv or s3://...")
    p.add_argument(
        "--weather", required=True, help="weather_normalized_full.csv or s3://..."
    )
    p.add_argument("--output", required=True, help="training_data.csv or s3://...")
    args = p.parse_args()

    build_training_data(
        args.pa,
        args.power,
        args.pitcher_stats,
        args.park_factors,
        args.weather,
        args.output,
    )
