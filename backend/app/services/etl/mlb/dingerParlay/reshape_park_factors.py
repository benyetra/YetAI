#!/usr/bin/env python3
import argparse
import sys
import pandas as pd

# ───────────────────────────────────────────────────────────────────────────
# Complete mapping from Savant’s “Team” field → 3-letter MLB abbrev (“park_id”), lowercase.
TEAM_TO_ABBR = {
    "D-backs": "ari",
    "Diamondbacks": "ari",
    "Braves": "atl",
    "Orioles": "bal",
    "Red Sox": "bos",
    "Cubs": "chc",
    "White Sox": "cws",
    "Reds": "cin",
    "Guardians": "cle",
    "Rockies": "col",
    "Tigers": "det",
    "Astros": "hou",
    "Royals": "kc",
    "Angels": "ana",
    "Dodgers": "lad",
    "Marlins": "mia",
    "Brewers": "mil",
    "Twins": "min",
    "Mets": "nym",
    "Yankees": "nyy",
    "Athletics": "oak",
    "Phillies": "phi",
    "Pirates": "pit",
    "Padres": "sd",
    "Giants": "sf",
    "Mariners": "sea",
    "Cardinals": "stl",
    "Rays": "tb",
    "Rangers": "tex",
    "Blue Jays": "tor",
    "Nationals": "was",
}
# ───────────────────────────────────────────────────────────────────────────


def main(raw_csv: str, output_csv: str):
    """
    Reads your raw park_factor.csv (with a “Year” column) and emits:
      park_id,park,year,hr_factor
    """
    df = pd.read_csv(raw_csv)

    # check required columns
    for col in ("Team", "Year", "Park Factor"):
        if col not in df.columns:
            sys.exit(f"Error: '{col}' column not found in {raw_csv}")

    rows = []
    for idx, row in df.iterrows():
        team = str(row["Team"]).strip()
        if team not in TEAM_TO_ABBR:
            print(
                f"Warning: unrecognized team '{team}' (row {idx}); skipping",
                file=sys.stderr,
            )
            continue

        park_id = TEAM_TO_ABBR[team]
        year = int(row["Year"])
        try:
            hr_factor = float(row["Park Factor"])
        except Exception:
            print(
                f"Warning: invalid Park Factor '{row['Park Factor']}' @ row {idx}; skipping",
                file=sys.stderr,
            )
            continue

        rows.append(
            {
                "park_id": park_id,
                "park": park_id,  # duplicates park_id so build_training_data can find either
                "year": year,
                "hr_factor": hr_factor,
            }
        )

    if not rows:
        sys.exit("Error: no valid park-factor rows parsed!")

    out = pd.DataFrame(rows)
    # drop duplicates if any
    out = out.drop_duplicates(subset=["park_id", "year"])
    # reorder columns
    out = out[["park_id", "park", "year", "hr_factor"]]
    out.to_csv(output_csv, index=False)
    print(f"Wrote {len(out)} park-factor rows → {output_csv}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Convert raw park-factor CSV into (park_id,park,year,hr_factor)"
    )
    p.add_argument(
        "--raw", required=True, help="Raw CSV with columns Team,Year,Park Factor"
    )
    p.add_argument("--output", required=True, help="Where to write park_factors.csv")
    args = p.parse_args()
    main(args.raw, args.output)
