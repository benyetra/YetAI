"""Fair-price consensus weights: export history close rows, build the seed, monthly refit.

DATABASE_URL comes from the environment (never printed).
  export-history --from 2025-11-01 --to 2026-04-12 --out rows.csv.gz
  seed --rows rows.csv.gz --out weights_seed.json
  refit [--today YYYY-MM-DD] [--apply]   (dry run unless --apply)
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.fair_price import weights as W  # noqa: E402

MARKETS = ["player_rebounds", "player_assists"]


def _session():
    from app.core.database import SessionLocal

    return SessionLocal()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export-history")
    e.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    e.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    e.add_argument("--out", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--rows", required=True)
    s.add_argument("--out", required=True)
    r = sub.add_parser("refit")
    r.add_argument("--today", type=date.fromisoformat, default=date.today())
    r.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "export-history":
        db = _session()
        try:
            rows = W.close_rows(db, a.start, a.end, MARKETS)
        finally:
            db.close()
        W.write_rows(a.out, rows)
        print({m: len(v) for m, v in rows.items()})
    elif a.cmd == "seed":
        rows = W.read_rows(a.rows)
        markets = {
            m: {
                "weights": res["weights"],
                "fitted": res["fitted"],
                "n_rows": len(rows[m]),
                "log_loss": res["log_loss"],
            }
            for m, res in W.fit(rows).items()
        }
        seed = {
            "version": "nba-2025-26-seed",
            "sport": W.NBA,
            "fitted_through": "2026-04-12",
            "source": "2025-26 history closes",
            "markets": markets,
        }
        Path(a.out).write_text(json.dumps(seed, indent=1, sort_keys=True) + "\n")
        print({m: v["n_rows"] for m, v in markets.items()})
    else:
        db = _session()
        try:
            print(json.dumps(W.refit(db, a.today, apply=a.apply), indent=1))
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
