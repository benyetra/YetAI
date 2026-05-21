"""ESPN WNBA scoreboard helpers — sibling of app/services/etl/nba/_espn.py.

ESPN's public scoreboard endpoint is the source of truth for which WNBA games
happened and which teams played. We return normalized rows with home/away team
names and final scores (when completed=True).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
)
ESPN_INJURIES = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/wnba/injuries"
)

EASTERN = ZoneInfo("America/New_York")


def now_eastern() -> datetime:
    return datetime.now(tz=EASTERN)


def _fmt_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_games(game_date: date) -> list[dict]:
    """Return one dict per game on `game_date`. Score fields are None until completed."""
    params = {"dates": _fmt_yyyymmdd(game_date)}
    r = requests.get(ESPN_SCOREBOARD, params=params, timeout=15)
    if r.status_code != 200:
        logger.warning("ESPN WNBA scoreboard returned %s", r.status_code)
        return []

    payload = r.json()
    out: list[dict] = []
    for event in payload.get("events", []):
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        completed = bool(comp.get("status", {}).get("type", {}).get("completed"))
        try:
            home_score = int(home.get("score")) if home.get("score") not in (None, "") else None
            away_score = int(away.get("score")) if away.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            home_score = None
            away_score = None

        out.append({
            "espn_event_id": event.get("id"),
            "game_time_utc": _parse_iso(event.get("date")),
            "home_team_id_espn": home.get("id"),
            "away_team_id_espn": away.get("id"),
            "home_team_name": home["team"].get("displayName"),
            "away_team_name": away["team"].get("displayName"),
            "home_score": home_score,
            "away_score": away_score,
            "completed": completed,
        })
    return out


def fetch_injuries() -> list[dict]:
    """Return current WNBA injury report rows from ESPN."""
    r = requests.get(ESPN_INJURIES, timeout=15)
    if r.status_code != 200:
        logger.warning("ESPN WNBA injuries returned %s", r.status_code)
        return []
    payload = r.json()
    out: list[dict] = []
    for team in payload.get("injuries", []):
        team_name = (team.get("displayName") or "").strip()
        for inj in team.get("injuries", []):
            athlete = inj.get("athlete") or {}
            out.append({
                "player_name": (athlete.get("displayName") or "").strip(),
                "team_name": team_name,
                "status": inj.get("status") or "Out",
                "injury_type": (inj.get("details") or {}).get("type"),
            })
    return out
