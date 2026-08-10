"""Refresh pred_nfl_game_lines from The Odds API."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from app.core.database import SessionLocal
from app.models.predictions_models import NFLGameLines
from app.services.etl.nba._espn import EASTERN, now_eastern
from app.services.etl.nfl.team_names import normalize_team_name

logger = logging.getLogger(__name__)

ODDS_API_KEY_ENV = "ODDS_API_KEY"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "americanfootball_nfl"

BOOKMAKER_PRIORITY = ["pinnacle", "fanduel", "draftkings", "betmgm"]


def normalize_game_teams(home_team: str, away_team: str) -> tuple[str, str]:
    """Normalize Odds API team names to canonical NFL display names."""
    return normalize_team_name(home_team), normalize_team_name(away_team)


def _odds_get(path: str, params: dict) -> list | dict | None:
    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{ODDS_API_KEY_ENV} env var is required")
    from app.services.odds_api_sync import sync_odds_get

    try:
        resp = sync_odds_get(
            f"{ODDS_BASE_URL}/{path}",
            params={"apiKey": api_key, **params},
            caller=f"etl.nfl.update_game_lines.{path}",
            timeout=30,
            raise_for_status=False,
        )
        if resp is None:
            return None
        if resp.status_code != 200:
            logger.warning(
                "odds-api %s returned %d: %s", path, resp.status_code, resp.text[:200]
            )
            return None
        return resp.json()
    except requests.RequestException:
        logger.exception("odds-api request failed: %s", path)
        return None


def _fetch_bulk_odds() -> list[dict]:
    data = _odds_get(
        f"{SPORT}/odds",
        {
            "regions": "us",
            "markets": "spreads,totals,h2h",
            "oddsFormat": "american",
            "bookmakers": ",".join(BOOKMAKER_PRIORITY),
        },
    )
    return data if isinstance(data, list) else []


def _parse_odds(odds_data: dict | None, home_team: str, away_team: str) -> dict:
    result = {
        "spread_home": None,
        "spread_away": None,
        "spread_home_odds": None,
        "spread_away_odds": None,
        "total": None,
        "over_odds": None,
        "under_odds": None,
        "moneyline_home": None,
        "moneyline_away": None,
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
    events = _fetch_bulk_odds()
    if not events:
        return {
            "status": "ok",
            "reason": "no_events_returned",
            "processed": 0,
            "updated": 0,
        }

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
                game_dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if game_dt.tzinfo is None:
                    game_dt = game_dt.replace(tzinfo=timezone.utc)
                game_date = game_dt.astimezone(EASTERN).date()
                if game_date not in (today, tomorrow):
                    continue

                processed += 1
                home_norm, away_norm = normalize_game_teams(home_team, away_team)

                odds = _parse_odds(game, home_team, away_team)

                existing = (
                    db.query(NFLGameLines)
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
                    db.add(
                        NFLGameLines(
                            game_date=game_date,
                            home_team_name=home_norm,
                            away_team_name=away_norm,
                            odds_api_event_id=event_id,
                            game_time=game_dt,
                            last_updated=datetime.utcnow(),
                            **odds,
                        )
                    )
                db.commit()
                upserted += 1
            except Exception:
                logger.exception("update_game_lines: failed event %s", game.get("id"))
                db.rollback()
                continue
        return {
            "status": "ok",
            "sport": SPORT,
            "events_returned": len(events),
            "processed_today_or_tomorrow": processed,
            "upserted": upserted,
        }
    finally:
        db.close()
