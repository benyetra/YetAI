#!/usr/bin/env python3
import argparse
import sys
import pandas as pd
import requests
from io import StringIO

def download_savant_3yr_park_factors(season: int, output_csv: str):
    """
    Scrape Baseball Savant’s “3-year rolling” Park Factors (Year view) for a given season.
    We fetch the HTML page, use pandas.read_html() to find the table, then extract:
        • Team  → park_id (lowercase)
        • Year  → ignored (we force 'year' = season)
        • HR    → 3-year rolling Home-Run factor (we call it HR_factor)
    We also create placeholder columns R_factor and BA_factor (all NaN), so
    that downstream code sees exactly these six columns in this order:

       park_id,park,year,HR_factor,R_factor,BA_factor

    Usage example:
        python download_park_factors.py \
          --season 2025 \
          --output scripts/mlb/dingerParlay/data/park_factors.csv
    """

    base_url = "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"
    params = {
        "type":      "year",          # “Year” view (3-year rolling)
        "year":      season,
        "batSide":   "",
        "stat":      "index_wOBA",
        "condition": "All",
        "rolling":   "3",
        "parks":     "mlb"
    }

    try:
        resp = requests.get(base_url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error: could not fetch Savant HTML page → {e}")
        sys.exit(1)

    html = resp.text

    # 1) Use pandas.read_html to parse all tables on the page
    try:
        tables = pd.read_html(StringIO(html), flavor="lxml")
    except Exception as e:
        print(f"Error: pandas.read_html failed on Savant HTML → {e}")
        sys.exit(1)

    # 2) Find the “park-factors” table by looking for columns "Team", "Year", and "HR"
    pf_table = None
    for tbl in tables:
        cols = [str(c).strip() for c in tbl.columns]
        if ("Team" in cols) and ("Year" in cols) and ("HR" in cols):
            pf_table = tbl.copy()
            break

    if pf_table is None:
        print("Error: could not locate a table containing ‘Team’, ‘Year’, and ‘HR’ columns.")
        sys.exit(1)

    # 3) Standardize column names to stripped strings
    pf_table.columns = [str(c).strip() for c in pf_table.columns]

    # 4) Verify that the required columns are present
    missing = [c for c in ("Team", "Year", "HR") if c not in pf_table.columns]
    if missing:
        print(f"Error: scraped table is missing required columns: {missing}")
        sys.exit(1)

    # 5) Build our output DataFrame with exactly:
    #       park_id,park,year,HR_factor,R_factor,BA_factor
    #    • park_id = lowercase of "Team"
    #    • park    = same as park_id
    #    • year    = integer `season`
    #    • HR_factor = numeric(“HR”)
    #    • R_factor  = placeholder NaN
    #    • BA_factor = placeholder NaN
    out = pd.DataFrame({
        "park_id":   pf_table["Team"].astype(str).str.strip().str.lower(),
        "park":      pf_table["Team"].astype(str).str.strip().str.lower(),
        "year":      [season] * len(pf_table),
        "HR_factor": pd.to_numeric(pf_table["HR"], errors="coerce"),
        "R_factor":  pd.NA,
        "BA_factor": pd.NA
    })

    # 6) Drop any rows where HR_factor couldn’t be parsed
    before = len(out)
    out = out.dropna(subset=["HR_factor"]).reset_index(drop=True)
    after = len(out)
    dropped = before - after
    if dropped > 0:
        print(f"Warning: dropped {dropped} rows because ‘HR’ was not numeric")

    # 7) Re-order columns exactly as downstream expects
    out = out[["park_id", "park", "year", "HR_factor", "R_factor", "BA_factor"]]

    # 8) Write to CSV
    try:
        out.to_csv(output_csv, index=False)
    except Exception as e:
        print(f"Error: could not write output CSV to '{output_csv}' → {e}")
        sys.exit(1)

    print(f"Wrote {len(out)} park factors → {output_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download 3-year rolling park factors (Year view) from Baseball Savant."
    )
    parser.add_argument(
        "--season", type=int, required=True,
        help="Season year (e.g. 2025)"
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to output CSV (e.g. data/park_factors.csv)"
    )
    args = parser.parse_args()

    download_savant_3yr_park_factors(args.season, args.output)
