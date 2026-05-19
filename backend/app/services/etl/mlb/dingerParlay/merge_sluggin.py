#!/usr/bin/env python3
import glob
import os
import sys
import pandas as pd

# S3 support
import boto3
from io import StringIO, BytesIO

def list_s3_files(bucket, prefix, pattern):
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    files = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".csv") and pattern in key:
                files.append(f"s3://{bucket}/{key}")
    return sorted(files)

def read_csv_s3(s3_uri):
    bucket = s3_uri.split("/")[2]
    key = "/".join(s3_uri.split("/")[3:])
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    return pd.read_csv(BytesIO(response["Body"].read()))

def write_csv_s3(df, s3_uri):
    bucket = s3_uri.split("/")[2]
    key = "/".join(s3_uri.split("/")[3:])
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
    print(f"🔗 Merged files → {s3_uri} ({len(df)} rows)")

def main(input_pattern="scripts/mlb/dingerParlay/data/slugging_*.csv", output_path="scripts/mlb/dingerParlay/data/slugging_all.csv"):
    # S3 or local?
    if input_pattern.startswith("s3://"):
        bucket = input_pattern.split("/")[2]
        prefix = "/".join(input_pattern.split("/")[3:-1])
        base_pattern = input_pattern.split("/")[-1].replace(".csv", "")
        # List all S3 slugging files
        paths = list_s3_files(bucket, prefix, base_pattern)
        read_csv = read_csv_s3
    else:
        paths = sorted(glob.glob(input_pattern))
        read_csv = pd.read_csv

    all_dfs = []
    for p in paths:
        if p.startswith("s3://"):
            year = int(p.rsplit("_", 1)[1].replace(".csv", ""))
            df = read_csv(p)
        else:
            year = int(os.path.basename(p).rsplit("_", 1)[1].replace(".csv", ""))
            df = read_csv(p)
        df["season"] = year
        all_dfs.append(df)

    if not all_dfs:
        print("No slugging CSV files found to merge!", file=sys.stderr)
        sys.exit(1)

    career = pd.concat(all_dfs, ignore_index=True)

    # Write to output
    if output_path.startswith("s3://"):
        write_csv_s3(career, output_path)
    else:
        career.to_csv(output_path, index=False)
        print(f"🔗 Merged {len(paths)} files → {output_path} ({len(career)} rows)")

if __name__=="__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Merge slugging_*.csv to slugging_all.csv (local or S3)")
    parser.add_argument("--input", default="scripts/mlb/dingerParlay/data/slugging_*.csv",
                        help="Glob or S3 URI pattern for input CSVs (e.g. s3://bucket/slugging/slugging_*.csv)")
    parser.add_argument("--output", default="scripts/mlb/dingerParlay/data/slugging_all.csv",
                        help="Output path (local file or s3://bucket/slugging_all.csv)")
    args = parser.parse_args()
    main(args.input, args.output)
