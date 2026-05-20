#!/usr/bin/env python3
import argparse
import logging
import pandas as pd
import boto3
from io import BytesIO


def read_csv_anywhere(path, **kwargs):
    """Load CSV from S3 or local disk (low_memory=False by default)."""
    if path.startswith("s3://"):
        bucket, key = path.split("/")[2], "/".join(path.split("/")[3:])
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        raw = obj["Body"].read()
        return pd.read_csv(BytesIO(raw), low_memory=False, **kwargs)
    else:
        return pd.read_csv(path, low_memory=False, **kwargs)


def main():
    parser = argparse.ArgumentParser(
        description="Check is_HR distribution in hold-out slice"
    )
    parser.add_argument(
        "--data", required=True, help="Path to full dataset CSV (local or s3://)"
    )
    parser.add_argument(
        "--start-date",
        default="2025-06-01",
        help="Inclusive start date for hold-out (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO
    )
    logging.info(f"Loading data from {args.data}")

    # Load data
    df = read_csv_anywhere(args.data, parse_dates=["game_date"])
    logging.info(f"Total rows in dataset: {len(df)}")

    # Filter hold-out
    test = df[df.game_date >= args.start_date]
    total = len(test)
    if total == 0:
        logging.error(f"No rows found on or after {args.start_date}")
        return

    # Distribution
    counts = test["is_HR"].value_counts().sort_index()
    percent = test["is_HR"].mean() * 100

    print(f"Hold-out slice (>= {args.start_date}) total samples: {total}")
    print("is_HR value counts:")
    print(counts.to_string())
    print(f"Percentage of HR events: {percent:.2f}%")


if __name__ == "__main__":
    main()
