#!/usr/bin/env python3
import pandas as pd
import sys
from pybaseball import statcast


def download_statcast_all(start_date, end_date, out_csv):
    try:
        df = statcast(start_date, end_date)
        df.to_csv(out_csv, index=False)
        print(f"Wrote {len(df)} rows (including barrel, etc.) to {out_csv}")
    except Exception as e:
        print(f"Error fetching statcast: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: download_all_statcast.py <start_date> <end_date> <out_csv>")
        sys.exit(1)
    _, START, END, OUT = sys.argv
    download_statcast_all(START, END, OUT)
