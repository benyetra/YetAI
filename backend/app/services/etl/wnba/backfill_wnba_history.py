"""One-shot historical backfill for pred_wnba_recent_games.

Pulls 2021-2025 regular-season box scores via nba_api (LeagueID=10) and
upserts one row per player-game into pred_wnba_recent_games.

Not registered as a Celery task — run manually:

    cd backend && ./.venv/bin/python -m app.services.etl.wnba.backfill_wnba_history

or via an admin endpoint. Re-runs are idempotent (upsert on
(player_id, game_date)).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from nba_api.stats.endpoints import (  # type: ignore
    boxscoretraditionalv2,
    leaguegamefinder,
)

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._wnba_stats import BACKOFF_SECONDS, LEAGUE_ID, _retry

logger = logging.getLogger(__name__)

DEFAULT_SEASONS: list[str] = ["2021", "2022", "2023", "2024", "2025"]


def _minutes_to_float(minutes_str: str | None) -> float | None:
    """ESPN/stats.nba MIN format is 'MM:SS' or 'MM.SS'. Return total minutes as float."""
    if not minutes_str:
        return None
    s = str(minutes_str).strip()
    try:
        if ":" in s:
            m, sec = s.split(":")
            return float(m) + float(sec) / 60.0
        return float(s)
    except (ValueError, AttributeError):
        return None


def _fetch_games_for_season(season: str) -> list[dict[str, Any]]:
    """Return one row per team-game for the WNBA season."""
    obj = leaguegamefinder.LeagueGameFinder(
        league_id_nullable=LEAGUE_ID,
        season_nullable=season,
        season_type_nullable="Regular Season",
    )
    return obj.get_normalized_dict()["LeagueGameFinderResults"]


def _fetch_boxscore(game_id: str) -> list[dict[str, Any]]:
    """Return one row per player for one game (traditional box score)."""
    obj = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
    return obj.get_normalized_dict()["PlayerStats"]


def run(seasons: list[str] | None = None) -> dict:
    seasons = seasons or DEFAULT_SEASONS
    db = SessionLocal()
    total_rows_written = 0
    total_games_processed = 0
    total_games_skipped = 0
    pending_rows: list[dict] = []

    def _flush_pending() -> None:
        nonlocal total_rows_written
        if not pending_rows:
            return
        upsert_many(
            db,
            WNBARecentGames,
            pending_rows,
            conflict_keys=["player_id", "game_date"],
        )
        total_rows_written += len(pending_rows)
        pending_rows.clear()

    try:
        for season in seasons:
            logger.info("backfill: fetching games for season %s", season)
            games = _fetch_games_for_season(season)
            # Group by GAME_ID so we can identify both teams per game.
            by_game: dict[str, list[dict[str, Any]]] = {}
            for g in games:
                by_game.setdefault(g["GAME_ID"], []).append(g)

            for game_id, teams in by_game.items():
                if not teams:
                    total_games_skipped += 1
                    continue
                team_a = teams[0]
                game_date_str = team_a.get("GAME_DATE")
                if not game_date_str:
                    total_games_skipped += 1
                    continue
                try:
                    game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
                except ValueError:
                    total_games_skipped += 1
                    continue

                # Determine home team from MATCHUP string. "X vs. Y" → X home; "X @ Y" → X away.
                home_team_id = None
                for t in teams:
                    if "vs." in (t.get("MATCHUP") or ""):
                        home_team_id = int(t["TEAM_ID"])
                        break

                try:
                    boxscore_rows = _retry(
                        lambda: _fetch_boxscore(game_id), f"boxscore({game_id})"
                    )
                except Exception as exc:
                    logger.warning(
                        "boxscore fetch failed for %s after retries: %s", game_id, exc
                    )
                    total_games_skipped += 1
                    continue

                if not boxscore_rows:
                    total_games_skipped += 1
                    continue

                # Build team_id → opponent map. Prefer the games list (2 rows per game);
                # fall back to deriving the two distinct TEAM_IDs from the boxscore rows.
                if len(teams) == 2:
                    team_b = teams[1]
                    team_id_to_opp = {
                        int(team_a["TEAM_ID"]): int(team_b["TEAM_ID"]),
                        int(team_b["TEAM_ID"]): int(team_a["TEAM_ID"]),
                    }
                else:
                    distinct_team_ids = list(
                        {
                            int(r["TEAM_ID"])
                            for r in boxscore_rows
                            if r.get("TEAM_ID") is not None
                        }
                    )
                    if len(distinct_team_ids) != 2:
                        total_games_skipped += 1
                        continue
                    t1, t2 = distinct_team_ids
                    team_id_to_opp = {t1: t2, t2: t1}

                for row in boxscore_rows:
                    player_id = row.get("PLAYER_ID")
                    if player_id is None:
                        continue
                    team_id = int(row["TEAM_ID"])
                    opp_id = team_id_to_opp.get(team_id)
                    if opp_id is None:
                        continue

                    pending_rows.append(
                        {
                            "player_id": int(player_id),
                            "game_date": game_date,
                            "opponent_team_id": opp_id,
                            "points": row.get("PTS"),
                            "fg_attempts": row.get("FGA"),
                            "fg_percentage": row.get("FG_PCT"),
                            "three_pt_attempts": row.get("FG3A"),
                            "three_pt_percentage": row.get("FG3_PCT"),
                            "three_pt_made": row.get("FG3M"),
                            "ft_attempts": row.get("FTA"),
                            "ft_percentage": row.get("FT_PCT"),
                            "minutes": _minutes_to_float(row.get("MIN")),
                            "field_goals_made": row.get("FGM"),
                            "free_throws_made": row.get("FTM"),
                            "offensive_rebounds": row.get("OREB"),
                            "defensive_rebounds": row.get("DREB"),
                            "rebounds": row.get("REB"),
                            "assists": row.get("AST"),
                            "turnovers": row.get("TOV"),
                            "steals": row.get("STL"),
                            "blocks": row.get("BLK"),
                            "personal_fouls": row.get("PF"),
                            "home_game": (home_team_id == team_id) if home_team_id else None,
                            "plus_minus": row.get("PLUS_MINUS"),
                        }
                    )

                total_games_processed += 1
                if total_games_processed % 50 == 0:
                    _flush_pending()
                    db.commit()
                    logger.info(
                        "backfill: %d games, %d rows written (season %s)",
                        total_games_processed,
                        total_rows_written,
                        season,
                    )

        _flush_pending()
        db.commit()
        return {
            "status": "ok",
            "seasons": seasons,
            "games_processed": total_games_processed,
            "games_skipped": total_games_skipped,
            "rows_written": total_rows_written,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2, default=str))
