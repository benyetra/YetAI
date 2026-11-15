"""Consensus book weights: the shipped seed, the monthly refit, and which set is active.

Close rows ({market: [(month, y, {book: p_over at the modal close line})]}) come from the
backtest's own loaders, so a refit fits exactly what the backtest fitted.
"""

from __future__ import annotations

import csv
import gzip
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from app.services.fair_price import backtest, consensus, lines

SEED_PATH = Path(__file__).with_name("weights_seed.json")
HISTORY_ROWS_PATH = Path(__file__).with_name("close_rows_2025_26.csv.gz")
EQUAL = "equal"
NBA = "basketball_nba"
LIVE_START = date(2026, 10, 1)  # first live-season close; history covers 2025-26

Rows = dict[str, list[tuple[str, int, dict[str, float]]]]


def close_rows(db, start: date, end: date, markets) -> Rows:
    """Close rows of NBA props with game_date in [start, end]."""
    params = backtest.Params()
    quotes = backtest.load_snapshots(db, markets, start, end)
    key_to_id, _ = backtest.load_player_keys(db)
    box = backtest.load_box(db, start, end)
    rows, _ = backtest.collect_close_rows(
        backtest._group(quotes), params, key_to_id, box
    )
    out: Rows = {}
    for (market, month), items in sorted(rows.items()):
        out.setdefault(market, []).extend((month, y, probs) for probs, y in items)
    return out


def write_rows(path, rows: Rows) -> None:
    with gzip.open(path, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["market", "month", "y", "probs"])
        for market in sorted(rows):
            for month, y, probs in rows[market]:
                packed = "|".join(f"{b}={probs[b]:.6f}" for b in sorted(probs))
                w.writerow([market, month, y, packed])


def read_rows(path) -> Rows:
    out: Rows = {}
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            probs = {
                b: float(p) for b, p in (kv.split("=") for kv in r["probs"].split("|"))
            }
            out.setdefault(r["market"], []).append((r["month"], int(r["y"]), probs))
    return out


def fit(rows_by_market: Rows, min_n: int = 300) -> dict:
    return {
        m: consensus.fit_weights([(p, y) for _, y, p in rows], min_n=min_n)
        for m, rows in rows_by_market.items()
    }


def _seed() -> dict:
    return json.loads(SEED_PATH.read_text()) if SEED_PATH.exists() else {}


def _seed_weights(sport: str, market: str) -> dict | None:
    seed = _seed()
    if seed.get("sport") != sport:
        return None
    m = seed.get("markets", {}).get(market)
    return m["weights"] if m else None


def _has_table(db) -> bool:
    from sqlalchemy import inspect

    return inspect(db.get_bind()).has_table("fair_price_weights")


def active(db, sport: str, market: str) -> tuple[dict | None, str]:
    """(weights, version): newest table row, else the seed, else (None, EQUAL)."""
    if _has_table(db):
        from app.models.predictions_models import FairPriceWeights as W

        row = (
            db.query(W)
            .filter(W.sport == sport, W.market == market)
            .order_by(W.fitted_through.desc(), W.id.desc())
            .first()
        )
        if row:
            return row.weights, row.version
    w = _seed_weights(sport, market)
    if w is not None:
        return w, _seed()["version"]
    return None, EQUAL


def by_version(db, version: str, sport: str, market: str) -> dict | None:
    if version == EQUAL:
        return None
    if SEED_PATH.exists() and version == _seed().get("version"):
        return _seed_weights(sport, market)
    if not _has_table(db):
        return None
    from app.models.predictions_models import FairPriceWeights as W

    row = (
        db.query(W)
        .filter(W.version == version, W.sport == sport, W.market == market)
        .first()
    )
    return row.weights if row else None


def refit(db, today: date, apply: bool = True) -> dict:
    """Fit history + live closes through the last day of the month before ``today`` and
    store one row per fitted market under version nba-YYYY-MM."""
    from app.models.predictions_models import FairPriceWeights as W

    end = today.replace(day=1) - timedelta(days=1)
    version = f"nba-{end:%Y-%m}"
    if db.query(W).filter(W.version == version).first():
        return {"status": "exists", "version": version}
    history = read_rows(HISTORY_ROWS_PATH)
    live = close_rows(db, LIVE_START, end, list(lines.PHI))
    merged = {
        m: history.get(m, []) + live.get(m, [])
        for m in sorted(set(history) | set(live))
    }
    out: dict = {"status": "dry-run", "version": version, "markets": {}}
    for market, res in fit(merged).items():
        # No live closes yet: the fit would only re-label the seed, so the seed stays.
        if not res["fitted"] or not live.get(market):
            continue
        out["markets"][market] = {
            "history_rows": len(history.get(market, [])),
            "live_rows": len(live.get(market, [])),
            "fitted": res["fitted"],
        }
        if apply:
            db.add(
                W(
                    version=version,
                    sport=NBA,
                    market=market,
                    weights=res["weights"],
                    fitted=res["fitted"],
                    n_rows=len(merged[market]),
                    fitted_through=end,
                    source="history+live",
                    created_at=datetime.utcnow(),
                )
            )
    if apply:
        db.commit()
        out["status"] = "applied"
    return out
