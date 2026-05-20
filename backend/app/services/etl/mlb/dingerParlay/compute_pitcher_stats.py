#!/usr/bin/env python3
import argparse
import sys
import pandas as pd

try:
    from pybaseball import pitching_stats as _raw_pitching_stats
except ImportError:
    _raw_pitching_stats = None
import statsapi  # for lookup_player and fetching throwing hand

# ---- S3 Support ----
import boto3
from io import StringIO


def smart_to_csv(df, path, **kwargs):
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


def fetch_pitch_hand_by_id(pid: int) -> str:
    """
    Fetch a pitcher's throwing hand ("R" or "L") by MLBAM ID.
    """
    try:
        rec = statsapi.lookup_player(pid)
        if rec and "pitchHand" in rec[0]:
            return rec[0]["pitchHand"]["code"]
        resp = statsapi.get("people", {"personIds": pid})
        people = resp.get("people", [])
        if people and "pitchHand" in people[0]:
            return people[0]["pitchHand"]["code"]
    except Exception:
        pass
    return pd.NA


def compute_pitcher_stats_for_season(season: int) -> pd.DataFrame:
    """
    Download raw seasonal pitching stats, compute HR9/K9,
    lookup MLBAM ID & hand (if available), and return a DataFrame
    with columns:
      pitcher_name, pitcher_id, pitcher_hand, HR9, K9, year
    """
    if _raw_pitching_stats is None:
        print(
            "Error: pybaseball.pitching_stats unavailable; install pybaseball.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 1) fetch raw season data
    try:
        raw = _raw_pitching_stats(season)
    except Exception as e:
        print(f"Error fetching pitching stats for {season}: {e}", file=sys.stderr)
        sys.exit(1)

    raw.columns = [str(c).strip() for c in raw.columns]

    # 2) identify pitcher_name
    if "player_name" in raw.columns:
        raw = raw.rename(columns={"player_name": "pitcher_name"})
    elif "Name" in raw.columns:
        raw = raw.rename(columns={"Name": "pitcher_name"})
    else:
        print(f"Error: No 'player_name' or 'Name' in raw for {season}", file=sys.stderr)
        sys.exit(1)

    # 3) ensure HR, SO, IP present
    for c in ("HR", "SO", "IP"):
        if c not in raw.columns:
            print(f"Error: Column '{c}' missing in season {season}", file=sys.stderr)
            sys.exit(1)

    # 4) numeric IP
    raw["IP"] = pd.to_numeric(raw["IP"], errors="coerce")

    # 5) compute rates
    raw["HR9"] = raw.apply(
        lambda r: (
            (9 * r["HR"] / r["IP"]) if pd.notna(r["IP"]) and r["IP"] > 0 else pd.NA
        ),
        axis=1,
    )
    raw["K9"] = raw.apply(
        lambda r: (
            (9 * r["SO"] / r["IP"]) if pd.notna(r["IP"]) and r["IP"] > 0 else pd.NA
        ),
        axis=1,
    )

    # 6) keep only those with valid rates
    df = raw[["pitcher_name", "HR9", "K9"]].dropna(subset=["HR9", "K9"]).copy()

    # 7) lookup IDs & hands (best-effort)
    pitcher_ids = {}
    pitcher_hands = {}
    for name in df["pitcher_name"].unique():
        pid = pd.NA
        hand = pd.NA
        try:
            hits = statsapi.lookup_player(name)
            if hits and isinstance(hits, list):
                pid = hits[0].get("id", pd.NA)
                if pd.notna(pid):
                    hand = fetch_pitch_hand_by_id(pid)
        except Exception:
            pass
        pitcher_ids[name] = pid
        pitcher_hands[name] = hand

    df["pitcher_id"] = df["pitcher_name"].map(pitcher_ids)
    df["pitcher_hand"] = df["pitcher_name"].map(pitcher_hands)

    # 8) attach year (season) for merging
    df["year"] = season

    print(f"  Season {season}: {len(df)} pitchers with HR9/K9")
    return df


def main():
    p = argparse.ArgumentParser(
        description="Compute multi-year pitcher stats (HR9, K9) + MLBAM ID & hand"
    )
    p.add_argument("--start", type=int, required=True, help="First season (e.g. 2013)")
    p.add_argument("--end", type=int, required=True, help="Last season  (e.g. 2025)")
    p.add_argument(
        "--output",
        required=True,
        help="Where to write pitcher_stats_all.csv (local or s3://)",
    )
    args = p.parse_args()

    if args.start > args.end:
        print("Error: --start must be ≤ --end", file=sys.stderr)
        sys.exit(1)

    all_seasons = []
    for season in range(args.start, args.end + 1):
        all_seasons.append(compute_pitcher_stats_for_season(season))

    result = pd.concat(all_seasons, ignore_index=True)
    smart_to_csv(result, args.output)
    # result.to_csv(args.output, index=False)
    # print(f"✅ Wrote {len(result)} total rows → {args.output}")


if __name__ == "__main__":
    main()
