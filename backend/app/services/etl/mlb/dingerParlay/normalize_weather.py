#!/usr/bin/env python3
import argparse
import sys
import pandas as pd
import os

# Optional: S3 support
try:
    import boto3
    from io import BytesIO, StringIO
except ImportError:
    boto3 = None

stadium_to_park = {
    "Truist Park": "atl",
    "Busch Stadium": "stl",
    "Rogers Centre": "tor",
    "T-Mobile Park": "sea",
    "Dodger Stadium": "lad",
    "PNC Park": "pit",
    "Nationals Park": "was",
    "Yankee Stadium": "nyy",
    "Oracle Park": "sf",
    "Wrigley Field": "chc",
    "Fenway Park": "bos",
    "Citi Field": "nym",
    "Kauffman Stadium": "kc",
    "Guaranteed Rate Field": "cws",
    "Rate Field": "cws",
    "Tropicana Field": "tb",
    "Globe Life Field": "tex",
    "Chase Field": "ari",
    "Minute Maid Park": "hou",
    "Great American Ball Park": "cin",
    "Progressive Field": "cle",
    "Coors Field": "col",
    "Comerica Park": "det",
    "LoanDepot Park": "mia",
    "Target Field": "min",
    "Oakland Coliseum": "oak",
    "Angel Stadium": "ana",
    "Globe Life Park": "tex",
    "Mariners Stadium": "sea",
    "Oriole Park at Camden Yards": "bal",
    "Petco Park": "sd",
    "American Family Field": "mil",
    "Sutter Health Park": "ath",
    "Daikin Park": "hou",
}


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
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=csv_buffer.getvalue()
        )
        print(f"Wrote normalized weather → {path} ({len(df)} rows)")
    else:
        df.to_csv(path, **kwargs)
        print(f"Wrote normalized weather → {path} ({len(df)} rows)")


def normalize_weather(raw_csv: str, output_csv: str):
    try:
        df = read_csv_anywhere(raw_csv, parse_dates=["date"])
    except ValueError as e:
        print(f"Error: Unable to read weather CSV '{raw_csv}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: could not read '{raw_csv}': {e}", file=sys.stderr)
        sys.exit(1)

    for required_col in ("park", "date", "tavg", "wspd"):
        if required_col not in df.columns:
            print(
                f"Error: raw weather CSV must contain column '{required_col}'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Map stadium → park_id, but preserve all rows
    df["park_id"] = df["park"].map(stadium_to_park)
    missing_map = df["park_id"].isna().sum()
    if missing_map > 0:
        print(
            f"Info: {missing_map} parks not found in stadium_to_park mapping. Using original stadium names as park_id.",
            file=sys.stderr,
        )
        df.loc[df["park_id"].isna(), "park_id"] = df.loc[df["park_id"].isna(), "park"]

    df = df.rename(columns={"tavg": "temp", "wspd": "wind_to_out"})

    out = df[["park_id", "date", "temp", "wind_to_out"]].copy()

    try:
        write_csv_anywhere(out, output_csv, index=False, date_format="%Y-%m-%d")
    except Exception as e:
        print(f"Error: could not write '{output_csv}': {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Take raw weather.csv and produce weather_normalized.csv for ML pipeline."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Raw weather CSV (park, date, tavg, wspd), local or S3.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Normalized weather CSV output path (local or S3).",
    )
    args = parser.parse_args()
    normalize_weather(args.input, args.output)
