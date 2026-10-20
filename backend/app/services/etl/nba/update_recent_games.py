"""Upsert per-game player stats into pred_recent_games (Development-1nt).

Port of YetiBets/scripts/nba/update_recent_games_api_sports_simple.py. For each
day in the window, hits api-sports /games to find game ids, then for each game
hits /players/statistics to pull box-score lines. Each line is keyed by
(player_id, game_date) and upserted into pred_recent_games.

The original script defaulted to a 30-day window. We default to 7 to be
gentler on api-sports quota in normal Beat-driven runs; the daily orchestrator
re-runs cover the rolling window naturally, and a one-off backfill can be
fired via the admin endpoint with days=30 once a manual-trigger path exists.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import RecentGames, TeamRoster
from app.services.etl.nba._api_sports import (
    API_SPORTS_TO_NBA,
    api_request,
    expand_player_name,
    resolve_nba_player_id,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._season import is_offseason_date

logger = logging.getLogger(__name__)


def is_nba_league_game(game: dict) -> bool:
    """API-Sports also carries Summer League leagues (vegas, utah, sacramento,
    orlando) and Africa games; keep only the NBA proper ("standard")."""
    league = game.get("league")
    return league is None or str(league).lower() == "standard"


def _num(value) -> float | None:
    """API-Sports stat value -> float. Missing / DNP placeholders ("--", "")
    become None; minutes may come as "32:15"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("+", "")
    if ":" in text:
        mins, _, secs = text.partition(":")
        try:
            return int(mins) + int(secs or 0) / 60
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


_STAT_FIELDS = {
    "points": "points",
    "minutes": "min",
    "field_goals_made": "fgm",
    "fg_attempts": "fga",
    "fg_percentage": "fgp",
    "three_pt_made": "tpm",
    "three_pt_attempts": "tpa",
    "three_pt_percentage": "tpp",
    "free_throws_made": "ftm",
    "ft_attempts": "fta",
    "ft_percentage": "ftp",
    "offensive_rebounds": "offReb",
    "defensive_rebounds": "defReb",
    "rebounds": "totReb",
    "assists": "assists",
    "steals": "steals",
    "blocks": "blocks",
    "turnovers": "turnovers",
    "personal_fouls": "pFouls",
}


def stat_line_fields(ps: dict, home_api_id, away_api_id) -> dict:
    """Map one API-Sports players/statistics line to RecentGames columns
    (minus player_id / game_date)."""
    player_team_api_id = (ps.get("team") or {}).get("id")
    is_home = player_team_api_id == home_api_id
    opponent_api_id = away_api_id if is_home else home_api_id
    fields = {column: _num(ps.get(key)) for column, key in _STAT_FIELDS.items()}
    return {
        "opponent_team_id": API_SPORTS_TO_NBA.get(opponent_api_id, 0),
        **fields,
        "home_game": is_home,
    }


def _process_day(target_date: date) -> tuple[int, int]:
    """Fetch games for a date, upsert stat lines. Returns (added, updated)."""
    if is_offseason_date(target_date):
        # Summer League / preseason box scores would poison every rolling
        # average (preseason starters play ~15-20 min) — never store them.
        logger.info("update_recent_games: %s is offseason, skipping", target_date)
        return 0, 0
    date_str = target_date.strftime("%Y-%m-%d")
    games_data = api_request("games", params={"date": date_str})
    if not games_data or not games_data.get("response"):
        logger.info("update_recent_games: no games on %s", date_str)
        return 0, 0

    games = games_data["response"]
    added = 0
    updated = 0

    db = SessionLocal()
    try:
        # Roster names (full names, from update_team_roster) let us expand
        # API-Sports box-score names like "C. Flagg" to the same player.
        roster_by_team: dict[int, list[str]] = {}
        for team_id, roster_name in db.query(
            TeamRoster.team_id, TeamRoster.player_name
        ):
            roster_by_team.setdefault(team_id, []).append(roster_name)
        league_names = [n for names in roster_by_team.values() for n in names]

        for game in games:
            if not is_nba_league_game(game):
                continue
            game_id = game["id"]
            home_api_id = (game.get("teams", {}).get("home") or {}).get("id")
            away_api_id = (game.get("teams", {}).get("visitors") or {}).get("id")

            stats_data = api_request("players/statistics", params={"game": game_id})
            if not stats_data or not stats_data.get("response"):
                continue

            for ps in stats_data["response"]:
                try:
                    player = ps.get("player") or {}
                    name = f"{(player.get('firstname') or '').strip()} {(player.get('lastname') or '').strip()}".strip()
                    team_nba_id = API_SPORTS_TO_NBA.get(
                        (ps.get("team") or {}).get("id")
                    )
                    name = expand_player_name(
                        name, roster_by_team.get(team_nba_id, []), league_names
                    )
                    nba_player_id = resolve_nba_player_id(
                        name, api_sports_id=player.get("id")
                    )
                    if not nba_player_id:
                        continue

                    stats = stat_line_fields(ps, home_api_id, away_api_id)
                    if stats["minutes"] is None:
                        continue  # did not play

                    existing = (
                        db.query(RecentGames)
                        .filter_by(player_id=nba_player_id, game_date=target_date)
                        .first()
                    )
                    if existing:
                        for k, v in stats.items():
                            setattr(existing, k, v)
                        updated += 1
                    else:
                        db.add(
                            RecentGames(
                                player_id=nba_player_id,
                                game_date=target_date,
                                **stats,
                            )
                        )
                        added += 1
                except Exception:
                    logger.exception(
                        "update_recent_games: failed line for game %s", game_id
                    )
                    db.rollback()
                    continue

            db.commit()
            time.sleep(0.1)

        return added, updated
    finally:
        db.close()


def run(days: int = 7) -> dict:
    """Fetch the last `days` days of player game stats (default 7).

    Caller can pass a larger window for a one-off backfill, but 7 is the
    daily-Beat-friendly default — 30 days × ~5-15 games/day × 1 API call per
    game adds up fast at API-Sports's quota.
    """
    end_date = now_eastern().date()
    start_date = end_date - timedelta(days=days)

    total_added = 0
    total_updated = 0
    current = start_date
    while current <= end_date:
        added, updated = _process_day(current)
        total_added += added
        total_updated += updated
        current += timedelta(days=1)
        time.sleep(0.2)

    return {
        "status": "ok",
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
        "days": days,
        "added": total_added,
        "updated": total_updated,
    }
