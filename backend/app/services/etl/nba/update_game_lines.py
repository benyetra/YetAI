"""Refresh pred_nba_game_lines from The Odds API (Development-1nt).

Port of YetiBets/scripts/nba/update_game_lines.py. Uses ODDS_API_KEY (already
on celery-worker for the games_sync task). Pulls spreads, totals, moneyline
for today + tomorrow from a priority bookmaker list.

Native datetime.fromisoformat() handles The Odds API's ISO commence_time —
no need for python-dateutil.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from app.core.database import SessionLocal
from app.models.predictions_models import NBAGameLines
from app.services.etl.nba._espn import EASTERN, now_eastern

logger = logging.getLogger(__name__)

ODDS_API_KEY_ENV = "ODDS_API_KEY"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "basketball_nba"

# A few Odds API team names are missing the "Los Angeles" prefix or use "LA".
# Normalize to the canonical name we store.
TEAM_NAME_FIX: dict[str, str] = {
    "LA Clippers": "Los Angeles Clippers",
    "LA Lakers": "Los Angeles Lakers",
}

BOOKMAKER_PRIORITY = ["pinnacle", "fanduel", "draftkings", "betmgm"]


def _normalize(name: str) -> str:
    return TEAM_NAME_FIX.get(name, name)


def _odds_get(path: str, params: dict) -> list | dict | None:
    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{ODDS_API_KEY_ENV} env var is required")
    try:
        r = requests.get(
            f"{ODDS_BASE_URL}/{path}",
            params={"apiKey": api_key, **params},
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning("odds-api %s returned %d: %s", path, r.status_code, r.text[:200])
            return None
        return r.json()
    except requests.RequestException:
        logger.exception("odds-api request failed: %s", path)
        return None


def _fetch_events() -> list[dict]:
    data = _odds_get(f"{SPORT}/events", {"dateFormat": "iso"})
    return data if isinstance(data, list) else []


def _fetch_odds_for(event_id: str) -> dict | None:
    return _odds_get(
        f"{SPORT}/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": "spreads,totals,h2h",
            "oddsFormat": "american",
            "bookmakers": ",".join(BOOKMAKER_PRIORITY),
        },
    )


def _parse_odds(odds_data: dict | None, home_team: str, away_team: str) -> dict:
    result = {
        "spread_home": None, "spread_away": None,
        "spread_home_odds": None, "spread_away_odds": None,
        "total": None, "over_odds": None, "under_odds": None,
        "moneyline_home": None, "moneyline_away": None,
        "bookmaker": None,
    }
    if not odds_data or "bookmakers" not in odds_data:
        return result
    for preferred in BOOKMAKER_PRIORITY:
        for bk in odds_data.get("bookmakers", []):
            if bk["key"].lower() != preferred:
                continue
            result["bookmaker"] = bk["title"]
            for market in bk.get("markets", []):
                key = market["key"]
                outcomes = market.get("outcomes", [])
                if key == "spreads":
                    for o in outcomes:
                        if o["name"] == home_team:
                            result["spread_home"] = o.get("point")
                            result["spread_home_odds"] = o.get("price")
                        elif o["name"] == away_team:
                            result["spread_away"] = o.get("point")
                            result["spread_away_odds"] = o.get("price")
                elif key == "totals":
                    for o in outcomes:
                        if o["name"] == "Over":
                            result["total"] = o.get("point")
                            result["over_odds"] = o.get("price")
                        elif o["name"] == "Under":
                            result["under_odds"] = o.get("price")
                elif key == "h2h":
                    for o in outcomes:
                        if o["name"] == home_team:
                            result["moneyline_home"] = o.get("price")
                        elif o["name"] == away_team:
                            result["moneyline_away"] = o.get("price")
            if result["spread_home"] is not None or result["total"] is not None:
                return result
    return result


def run() -> dict:
    events = _fetch_events()
    if not events:
        return {"status": "ok", "reason": "no_events_returned", "processed": 0, "updated": 0}

    today = now_eastern().date()
    tomorrow = today + timedelta(days=1)

    processed = 0
    upserted = 0

    db = SessionLocal()
    try:
        for game in events:
            try:
                event_id = game["id"]
                home_team = game.get("home_team", "")
                away_team = game.get("away_team", "")
                ct = game.get("commence_time", "")
                if not ct:
                    continue
                # The Odds API returns ISO with trailing 'Z' which Python <3.11 chokes on;
                # we're on 3.11+ and fromisoformat handles 'Z' since 3.11.
                game_dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if game_dt.tzinfo is None:
                    game_dt = game_dt.replace(tzinfo=timezone.utc)
                game_date = game_dt.astimezone(EASTERN).date()
                if game_date not in (today, tomorrow):
                    continue

                processed += 1
                home_norm = _normalize(home_team)
                away_norm = _normalize(away_team)

                odds = _parse_odds(_fetch_odds_for(event_id), home_team, away_team)

                existing = (
                    db.query(NBAGameLines)
                    .filter_by(
                        game_date=game_date,
                        home_team_name=home_norm,
                        away_team_name=away_norm,
                    )
                    .first()
                )
                if existing:
                    existing.odds_api_event_id = event_id
                    existing.game_time = game_dt
                    for k, v in odds.items():
                        setattr(existing, k, v)
                    existing.last_updated = datetime.utcnow()
                else:
                    db.add(NBAGameLines(
                        game_date=game_date,
                        home_team_name=home_norm,
                        away_team_name=away_norm,
                        odds_api_event_id=event_id,
                        game_time=game_dt,
                        last_updated=datetime.utcnow(),
                        **odds,
                    ))
                db.commit()
                upserted += 1
            except Exception:
                logger.exception("update_game_lines: failed event %s", game.get("id"))
                db.rollback()
                continue
        return {
            "status": "ok",
            "events_returned": len(events),
            "processed_today_or_tomorrow": processed,
            "upserted": upserted,
        }
    finally:
        db.close()
