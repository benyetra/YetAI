"""Refresh pred_wnba_game_lines from The Odds API.

Stores ONE consensus row per game (simple average across all books that offer
the market). This differs from the NBA equivalent which stores per-book rows.
Spec: docs/superpowers/specs/2026-05-21-wnba-support-design.md (Section 4c).
"""

from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime

import requests

from app.core.database import SessionLocal
from app.models.predictions_models import WNBAGameLines
from app.services.etl.wnba._espn import EASTERN
from app.services.etl.wnba._team_id_map import name_to_wnba_id, normalize_team_name

logger = logging.getLogger(__name__)

ODDS_API_KEY_ENV = "ODDS_API_KEY"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "basketball_wnba"


def _odds_get(path: str, params: dict) -> list | dict | None:
    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{ODDS_API_KEY_ENV} env var is required")
    r = requests.get(
        f"{ODDS_BASE_URL}/{path}",
        params={"apiKey": api_key, **params},
        timeout=20,
    )
    if r.status_code != 200:
        logger.warning("odds-api %s -> %s: %s", path, r.status_code, r.text[:200])
        return None
    return r.json()


def _consensus(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return statistics.mean(vals)


def _consensus_int(values: list) -> int | None:
    avg = _consensus(values)
    return int(round(avg)) if avg is not None else None


def _extract_market(book: dict, market_key: str) -> dict | None:
    for m in book.get("markets", []):
        if m.get("key") == market_key:
            return m
    return None


def run() -> dict:
    payload = _odds_get(
        f"{SPORT}/odds",
        params={
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        },
    )
    if not isinstance(payload, list):
        return {"status": "no_data", "games": 0}

    db = SessionLocal()
    games_written = 0
    try:
        for event in payload:
            home_raw = event.get("home_team") or ""
            away_raw = event.get("away_team") or ""
            home_name = normalize_team_name(home_raw)
            away_name = normalize_team_name(away_raw)
            if not home_name or not away_name:
                continue

            commence = datetime.fromisoformat(
                event["commence_time"].replace("Z", "+00:00")
            )
            game_date = commence.astimezone(EASTERN).date()

            spread_home_vals: list[float] = []
            spread_away_vals: list[float] = []
            spread_home_odds_vals: list[int] = []
            spread_away_odds_vals: list[int] = []
            total_vals: list[float] = []
            over_odds_vals: list[int] = []
            under_odds_vals: list[int] = []
            ml_home_vals: list[int] = []
            ml_away_vals: list[int] = []

            for book in event.get("bookmakers", []):
                spreads = _extract_market(book, "spreads")
                if spreads:
                    for o in spreads["outcomes"]:
                        if o["name"] == home_raw:
                            spread_home_vals.append(o["point"])
                            if o.get("price") is not None:
                                spread_home_odds_vals.append(o["price"])
                        elif o["name"] == away_raw:
                            spread_away_vals.append(o["point"])
                            if o.get("price") is not None:
                                spread_away_odds_vals.append(o["price"])
                totals = _extract_market(book, "totals")
                if totals:
                    for o in totals["outcomes"]:
                        if o["name"] == "Over":
                            total_vals.append(o["point"])
                            if o.get("price") is not None:
                                over_odds_vals.append(o["price"])
                        elif o["name"] == "Under":
                            if o.get("price") is not None:
                                under_odds_vals.append(o["price"])
                ml = _extract_market(book, "h2h")
                if ml:
                    for o in ml["outcomes"]:
                        if o["name"] == home_raw and o.get("price") is not None:
                            ml_home_vals.append(o["price"])
                        elif o["name"] == away_raw and o.get("price") is not None:
                            ml_away_vals.append(o["price"])

            obj = WNBAGameLines(
                game_date=game_date,
                home_team_id=name_to_wnba_id(home_name),
                away_team_id=name_to_wnba_id(away_name),
                home_team_name=home_name,
                away_team_name=away_name,
                odds_api_event_id=event.get("id"),
                game_time=commence,
                spread_home=_consensus(spread_home_vals),
                spread_away=_consensus(spread_away_vals),
                spread_home_odds=_consensus_int(spread_home_odds_vals),
                spread_away_odds=_consensus_int(spread_away_odds_vals),
                total=_consensus(total_vals),
                over_odds=_consensus_int(over_odds_vals),
                under_odds=_consensus_int(under_odds_vals),
                moneyline_home=_consensus_int(ml_home_vals),
                moneyline_away=_consensus_int(ml_away_vals),
                bookmaker="consensus",
                last_updated=datetime.utcnow(),
            )
            db.merge(obj)
            games_written += 1
        db.commit()
        return {"status": "ok", "games": games_written}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
