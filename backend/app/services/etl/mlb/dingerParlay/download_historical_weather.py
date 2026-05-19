#!/usr/bin/env python3
"""
Back-fill your normalized weather with historical daily data from Meteostat,
skipping any parks without coords rather than crashing on KeyError.
"""
import argparse
import sys
import pandas as pd
from datetime import timedelta
from meteostat import Daily, Point

# S3 write helper
import boto3
from io import StringIO

def smart_to_csv(df, path, **kwargs):
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

def fetch_daily_weather(lat, lon, start, end):
    """
    Fetch daily weather from Meteostat for the given bounding dates (inclusive).
    Returns DataFrame with columns ['date','tavg','tmin','tmax','wspd'].
    """
    pt = Point(lat, lon)
    df = Daily(pt, start, end + timedelta(days=1)).fetch()
    # bring the index into a column, rename its name → 'date'
    idx_name = df.index.name or 'index'
    df = df.reset_index().rename(columns={idx_name: 'date'})
    # keep only the 4 we care about
    return df[['date','tavg','tmin','tmax','wspd']]

def main():
    p = argparse.ArgumentParser(
        description="Download historical weather & merge with existing normals"
    )
    p.add_argument("--training", required=True,
                   help="Your training_data.csv (to get the date span & park_ids)")
    p.add_argument("--coords",   required=True,
                   help="park_coords.csv (park_id,lat,lon)")
    p.add_argument("--existing", required=True,
                   help="weather_normalized.csv you already have")
    p.add_argument("--output",   required=True,
                   help="Where to write weather_normalized_full.csv (can be s3://...)")
    args = p.parse_args()

    # 1) get park list & date range from training_data
    df_pa = pd.read_csv(args.training, parse_dates=["game_date"])
    if "park_id" not in df_pa.columns:
        sys.exit("Error: training_data.csv must have 'park_id'")
    parks = df_pa['park_id'].str.lower().unique().tolist()
    start = df_pa['game_date'].min()
    end   = df_pa['game_date'].max()

    # 2) load coords
    df_coords = pd.read_csv(args.coords)
    for c in ("park_id","lat","lon"):
        if c not in df_coords.columns:
            sys.exit(f"Error: park_coords.csv needs column '{c}'")
    df_coords['park_id'] = df_coords['park_id'].str.lower()
    df_coords = df_coords.set_index('park_id')

    # 3) load existing normalized weather
    df_exist = pd.read_csv(args.existing, parse_dates=["game_date"])
    must = {"park_id","game_date","temp","wind_to_out"}
    if not must.issubset(df_exist.columns):
        sys.exit(f"Error: existing CSV needs columns {must}")
    df_exist = (
        df_exist
        .rename(columns={
            "game_date":"date",
            "temp":     "tavg",
            "wind_to_out":"wspd"
        })[['park_id','date','tavg','wspd']]
    )
    df_exist['park_id'] = df_exist['park_id'].str.lower()
    # fill tmin/tmax so schema matches historical
    df_exist['tmin'] = df_exist['tavg']
    df_exist['tmax'] = df_exist['tavg']

    # 4) build the full park×date grid
    all_dates = pd.date_range(start, end, freq='D')
    grid = pd.MultiIndex.from_product([parks, all_dates],
                                      names=['park_id','date'])
    df_full = pd.DataFrame(index=grid).reset_index()

    # 5) merge in your existing normals
    df_full = df_full.merge(df_exist,
                            on=['park_id','date'],
                            how='left')

    # 6) back‐fill any holes
    to_fill = df_full[df_full['tavg'].isna()]
    if not to_fill.empty:
        print(f"⚡︎ Will fetch historical for {len(to_fill)} missing park-days…")
        fetched = []
        for pid, sub in to_fill.groupby('park_id'):
            if pid not in df_coords.index:
                print(f"  ⚠️  No coords for park_id='{pid}', skipping")
                continue
            lat, lon = df_coords.loc[pid, ['lat','lon']]
            hist = fetch_daily_weather(lat, lon, start, end)
            hist['park_id'] = pid
            fetched.append(hist)

        if fetched:
            df_hist = pd.concat(fetched, ignore_index=True)
            # merge historical in
            df_full = df_full.merge(
                df_hist,
                on=['park_id','date'],
                how='left',
                suffixes=('','_hist')
            )
            # coalesce existing → historical
            for col in ('tavg','tmin','tmax','wspd'):
                df_full[col] = df_full[col].combine_first(df_full[f'{col}_hist'])
            # drop the helper cols
            df_full = df_full.loc[:, ~df_full.columns.str.endswith('_hist')]

    # 7) final sanity check
    missing = df_full['tavg'].isna().sum()
    if missing:
        print(f"⚠️ Still {missing} missing after fetch!")
    else:
        print("✅ All park-days now have weather.")

    smart_to_csv(df_full, args.output, date_format='%Y-%m-%d')

if __name__ == '__main__':
    main()
