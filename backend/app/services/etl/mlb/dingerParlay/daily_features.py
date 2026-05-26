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
        key = "/".join(path.split("/")[3:])
        return read_s3_csv(bucket, key, **kwargs)
    return pd.read_csv(path, **kwargs)


def write_s3_csv(df, path):
    csv = df.to_csv(index=False)
    bucket, key = path.split("/")[2], "/".join(path.split("/")[3:])
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def build_daily_features(
    lineup_path: str,
    power_scores_path: str,
    pitcher_stats_path: str,
    park_factors_path: str,
    weather_path: str,
    output_path: str,
) -> int:
    """Merge lineup + static S3 artifacts into daily feature rows. Returns row count."""
    log("Loading today’s lineup")
    df = smart_read_csv(lineup_path, parse_dates=["game_date"])
    if "pitcher_hand" not in df.columns:
        sys.exit("Error: your lineup.csv must include a 'pitcher_hand' column")
    df = df.rename(columns={"pitcher_hand": "starter_hand"})
    df = df.drop_duplicates(subset=["batter_id", "pitcher_id", "park_id"])
    df["year"] = df["game_date"].dt.year

    # 2) merge PowerScore
    log("Merging PowerScore")
    ps = smart_read_csv(power_scores_path)
    df = df.merge(
        ps[["player_id", "PowerScore"]],
        left_on="batter_id",
        right_on="player_id",
        how="left",
    ).drop(columns="player_id")
    df = df.dropna(subset=["PowerScore"])

    # Optional ProfileStore contact edge (Phase 4; single source with hits board)
    try:
        from app.services.etl.mlb.profiles.constants import mlb_profiles_enabled
        from app.services.etl.mlb.profiles.matchup_contact import contact_matchup_score
        from app.services.etl.mlb.profiles.profile_store import ProfileStore
        from app.core.database import SessionLocal

        if mlb_profiles_enabled() and SessionLocal is not None:
            session = SessionLocal()
            try:
                store = ProfileStore(session)
                scores = []
                for row in df.itertuples(index=False):
                    d, _ = contact_matchup_score(
                        store,
                        int(row.batter_id),
                        int(row.pitcher_id),
                        str(row.starter_hand)[0].upper(),
                        (
                            row.game_date.date()
                            if hasattr(row.game_date, "date")
                            else row.game_date
                        ),
                    )
                    scores.append(d)
                df["matchup_contact_score"] = scores
                log("Merged ProfileStore matchup_contact_score")
            finally:
                session.close()
        else:
            df["matchup_contact_score"] = None
    except Exception as exc:
        log(f"Profile contact merge skipped: {exc}")
        df["matchup_contact_score"] = None

    # 3) merge pitcher HR9, K9
    log("Merging PitcherStats")
    pstats = smart_read_csv(pitcher_stats_path)
    df = df.merge(pstats[["pitcher_id", "HR9", "K9"]], on="pitcher_id", how="left")
    df = df.dropna(subset=["HR9", "K9"])

    # 4) merge park factors
    log("Merging ParkFactors")
    parks = smart_read_csv(park_factors_path)
    df = df.merge(
        parks[["park_id", "year", "hr_factor"]], on=["park_id", "year"], how="left"
    )
    df["hr_factor"] = df["hr_factor"].fillna(1.0)

    # 5) merge weather
    log("Merging Weather")
    w = smart_read_csv(weather_path, parse_dates=["game_date"])
    if "wind_to_out" in w.columns and "wind_speed" not in w.columns:
        w["wind_speed"] = w["wind_to_out"]
    w = w.drop_duplicates(subset=["park_id", "game_date"])
    df = df.merge(
        w[["park_id", "game_date", "temp", "wind_speed"]],
        on=["park_id", "game_date"],
        how="left",
    )
    df["temp"] = df["temp"].fillna(w["temp"].median())
    df["wind_speed"] = df["wind_speed"].fillna(0.0)

    # 6) compute platoon
    log("Computing platoon")
    df["platoon"] = (
        df["batter_hand"].str.upper() != df["starter_hand"].str.upper()
    ).astype(int)

    # 7) select only the 7 model features + IDs
    feats = ["PowerScore", "HR9", "K9", "hr_factor", "temp", "wind_speed", "platoon"]
    missing = set(feats) - set(df.columns)
    if missing:
        logging.error(f"Missing columns for model: {missing}")
        sys.exit(1)

    out = df[["batter_id", "pitcher_id", "park_id", "game_date"] + feats]

    log(f"Writing {len(out)} rows to {output_path}")
    if output_path.startswith("s3://"):
        write_s3_csv(out, output_path)
    else:
        out.to_csv(output_path, index=False)

    log("Done.")
    return len(out)


def main():
    p = argparse.ArgumentParser(description="Build daily feature file for HR model")
    p.add_argument("--lineup", required=True, help="today_lineup.csv")
    p.add_argument("--power-scores", required=True, help="power_scores.csv")
    p.add_argument("--pitcher-stats", required=True, help="pitcher_stats.csv")
    p.add_argument("--park-factors", required=True, help="park_factors.csv")
    p.add_argument("--weather", required=True, help="weather_normalized.csv")
    p.add_argument("--output", required=True, help="where to save daily_features.csv")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )
    build_daily_features(
        lineup_path=args.lineup,
        power_scores_path=args.power_scores,
        pitcher_stats_path=args.pitcher_stats,
        park_factors_path=args.park_factors,
        weather_path=args.weather,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
