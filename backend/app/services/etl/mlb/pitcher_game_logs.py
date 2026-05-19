"""Fetch pitcher game logs and persist to pred_historical_pitcher_stats."""
import logging
from datetime import datetime

import requests
import statsapi
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.models.predictions_models import HistoricalPitcherStats
from app.services.etl.mlb._db import db_session

logger = logging.getLogger(__name__)


def fetch_pitcher_game_logs(pitcher_id):
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}"
        f"?hydrate=stats(group=[pitching],type=[gameLog],season=2025"
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    if "people" not in data or not data["people"]:
        return []
    stats = data["people"][0].get("stats") or []
    for stat in stats:
        if stat.get("type", {}).get("displayName") == "gameLog" and stat.get("group", {}).get("displayName") == "pitching":
            return stat.get("splits") or []
    return []


def safe_divide(numerator, denominator):
    return numerator / denominator if denominator != 0 else 0


def calculate_metrics(game_logs, game_date):
    relevant_logs = [log for log in game_logs if log["date"] == game_date]
    if not relevant_logs:
        return None, None, None, None, None

    log = relevant_logs[0]
    stat = log.get("stat") or {}
    innings_pitched = float(stat.get("inningsPitched", 0) or 0)
    strikeouts = stat.get("strikeOuts", 0) or 0
    at_bats = stat.get("atBats", 0) or 0
    walks = stat.get("baseOnBalls", 0) or 0
    hits = stat.get("hits", 0) or 0
    return innings_pitched, strikeouts, at_bats, walks, hits


def calculate_metrics_actuals_v_projections(game_logs, game_date):
    for log in game_logs:
        log["date"] = datetime.strptime(log["date"], "%Y-%m-%d").date()

    relevant_logs = [log for log in game_logs if log["date"] == game_date]
    if not relevant_logs:
        return None, None, None, None, None

    log = relevant_logs[0]
    stat = log.get("stat") or {}
    innings_pitched = float(stat.get("inningsPitched", 0) or 0)
    strikeouts = stat.get("strikeOuts", 0) or 0
    at_bats = stat.get("atBats", 0) or 0
    walks = stat.get("baseOnBalls", 0) or 0
    hits = stat.get("hits", 0) or 0
    return innings_pitched, strikeouts, at_bats, walks, hits


def get_todays_games():
    today = datetime.today().date().strftime("%Y-%m-%d")
    return statsapi.schedule(date=today)


def fetch_todays_pitchers():
    schedule = get_todays_games()
    pitchers = []

    for game in schedule:
        for team in ["home", "away"]:
            probable_pitcher_key = f"{team}_probable_pitcher"
            if probable_pitcher_key not in game:
                continue
            pitcher_name = game[probable_pitcher_key]
            team_name_key = f"{team}_name"
            opponent_team = "away" if team == "home" else "home"
            game_date = game["game_date"]

            try:
                pitcher_id = statsapi.lookup_player(pitcher_name)[0]["id"]
            except (IndexError, KeyError):
                logger.warning("Could not resolve pitcher id for %s", pitcher_name)
                continue

            try:
                pitcher_stats_data = statsapi.player_stat_data(
                    pitcher_id, group="pitching", type="career", sportId=1
                )
                pitch_hand = pitcher_stats_data.get("pitch_hand", "Unknown")
            except KeyError:
                pitch_hand = "Unknown"

            pitchers.append(
                {
                    "name": pitcher_name,
                    "pitcher_id": pitcher_id,
                    "pitch_hand": pitch_hand,
                    "team": game[team_name_key],
                    "opponent": game[f"{opponent_team}_name"],
                    "game_date": game_date,
                }
            )
    return pitchers


def fetch_days_pitchers(date):
    schedule = statsapi.schedule(date)
    pitchers = []

    for game in schedule:
        for team in ["home", "away"]:
            probable_pitcher_key = f"{team}_probable_pitcher"
            if probable_pitcher_key not in game:
                continue
            pitcher_name = game[probable_pitcher_key]
            team_name_key = f"{team}_name"
            opponent_team = "away" if team == "home" else "home"
            game_date = game["game_date"]

            try:
                pitcher_id = statsapi.lookup_player(pitcher_name)[0]["id"]
            except (IndexError, KeyError):
                logger.warning("Could not resolve pitcher id for %s", pitcher_name)
                continue

            try:
                pitcher_stats_data = statsapi.player_stat_data(
                    pitcher_id, group="pitching", type="season"
                )
                pitch_hand = pitcher_stats_data.get("pitch_hand", "Unknown")
            except KeyError:
                pitch_hand = "Unknown"

            pitchers.append(
                {
                    "name": pitcher_name,
                    "pitcher_id": pitcher_id,
                    "pitch_hand": pitch_hand,
                    "team": game[team_name_key],
                    "opponent": game[f"{opponent_team}_name"],
                    "game_date": game_date,
                }
            )
    return pitchers


def _insert_historical_stat(pitcher: dict, game_log: dict, season: int) -> bool:
    """Insert one game log row. Returns True if inserted, False if duplicate."""
    stat = game_log.get("stat") or {}
    date_str = game_log["date"]
    game_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    opponent = (game_log.get("team") or {}).get("name", "")

    innings_pitched, strikeouts, at_bats, walks, hits = calculate_metrics(
        [game_log], date_str
    )
    if innings_pitched is None:
        return False

    walks = walks if walks is not None else 0
    whip = safe_divide(walks + hits, innings_pitched)

    existing = db_session.execute(
        text(
            "SELECT id FROM pred_historical_pitcher_stats "
            "WHERE player_id = :pid AND date = :dt LIMIT 1"
        ),
        {"pid": pitcher["pitcher_id"], "dt": game_date},
    ).scalar()
    if existing:
        return False

    row = HistoricalPitcherStats(
        player_id=pitcher["pitcher_id"],
        name=pitcher["name"],
        pitch_hand=pitcher["pitch_hand"],
        season=season,
        date=game_date,
        strikeouts=int(strikeouts or 0),
        innings_pitched=innings_pitched,
        opponent_team=opponent,
        at_bats=int(at_bats or 0),
        walks=int(walks),
        hits=int(hits or 0),
        baseOnBalls=int(walks),
        whip=whip,
        numberOfPitches=int(stat.get("numberOfPitches", 0) or 0),
    )
    db_session.add(row)
    return True


def ingest_todays_pitchers() -> dict:
    """Persist today's probable pitchers' game logs into pred_historical_pitcher_stats."""
    season = datetime.today().year
    pitchers = fetch_todays_pitchers()
    inserted = 0
    skipped = 0

    for pitcher in pitchers:
        try:
            game_logs = fetch_pitcher_game_logs(pitcher["pitcher_id"])
            for game_log in game_logs:
                if _insert_historical_stat(pitcher, game_log, season):
                    inserted += 1
                else:
                    skipped += 1
        except SQLAlchemyError as e:
            logger.warning(
                "DB error for pitcher %s: %s", pitcher.get("name"), e
            )
            db_session.rollback()
        except Exception as e:
            logger.warning("Error processing pitcher %s: %s", pitcher.get("name"), e)

    db_session.commit()
    logger.info("Historical pitcher stats: inserted=%s skipped=%s", inserted, skipped)
    return {"status": "ok", "inserted": inserted, "skipped": skipped}


def run() -> dict:
    """Celery entry: ingest today's pitcher game logs."""
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        return ingest_todays_pitchers()
    finally:
        close_session()


if __name__ == "__main__":
    ingest_todays_pitchers()
