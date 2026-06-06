"""Nightly upsert of recent WNBA box scores into pred_wnba_recent_games.

Pulls the last 2 days (Eastern) of games and re-runs the same per-game box
score path as backfill_wnba_history. Idempotent via upsert on (player_id, game_date).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from nba_api.stats.endpoints import leaguegamefinder  # type: ignore

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._boxscore_fetch import (
    advanced_by_player_id,
    fetch_advanced_boxscore,
    player_game_row_from_boxscore,
)
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba.backfill_wnba_history import _fetch_boxscore
from app.services.etl.wnba._wnba_stats import StatsNbaUnavailable

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 2


def _process_day(db, target_date: date) -> int:
    """Pull games for target_date, write rows to pred_wnba_recent_games."""
    date_str = target_date.strftime("%Y-%m-%d")
    finder = leaguegamefinder.LeagueGameFinder(
        league_id_nullable="10",
        date_from_nullable=date_str,
        date_to_nullable=date_str,
    )
    games = finder.get_normalized_dict()["LeagueGameFinderResults"]
    if not games:
        return 0

    by_game: dict[str, list[dict]] = {}
    for g in games:
        by_game.setdefault(g["GAME_ID"], []).append(g)

    upsert_rows: list[dict] = []
    for game_id, teams in by_game.items():
        if len(teams) != 2:
            # Fallback: derive opponent map from boxscore rows
            try:
                boxscore_rows = _fetch_boxscore(game_id, profile="default")
            except StatsNbaUnavailable as exc:
                logger.warning(
                    "boxscore fetch failed for %s after retries: %s", game_id, exc
                )
                continue

            distinct_team_ids = list(
                {
                    int(r["TEAM_ID"])
                    for r in boxscore_rows
                    if r.get("TEAM_ID") is not None
                }
            )
            if len(distinct_team_ids) != 2:
                continue
            t1, t2 = distinct_team_ids
            team_id_to_opp = {t1: t2, t2: t1}
        else:
            team_a, team_b = teams
            team_id_to_opp = {
                int(team_a["TEAM_ID"]): int(team_b["TEAM_ID"]),
                int(team_b["TEAM_ID"]): int(team_a["TEAM_ID"]),
            }

        home_team_id = None
        for t in teams:
            if "vs." in (t.get("MATCHUP") or ""):
                home_team_id = int(t["TEAM_ID"])

        try:
            boxscore_rows = _fetch_boxscore(game_id, profile="default")
        except StatsNbaUnavailable as exc:
            logger.warning(
                "boxscore fetch failed for %s after retries: %s", game_id, exc
            )
            continue

        try:
            adv_rows = fetch_advanced_boxscore(game_id, profile="default")
        except StatsNbaUnavailable as exc:
            logger.warning("advanced boxscore fetch failed for %s: %s", game_id, exc)
            adv_rows = []
        adv_map = advanced_by_player_id(adv_rows)

        for row in boxscore_rows:
            player_id = row.get("PLAYER_ID")
            if player_id is None:
                continue
            team_id = int(row["TEAM_ID"])
            opp_id = team_id_to_opp.get(team_id)
            if opp_id is None:
                continue
            upsert_rows.append(
                player_game_row_from_boxscore(
                    row,
                    game_date=target_date,
                    opponent_team_id=opp_id,
                    home_game=(home_team_id == team_id) if home_team_id else None,
                    adv_row=adv_map.get(int(player_id)),
                )
            )
    if upsert_rows:
        upsert_many(
            db,
            WNBARecentGames,
            upsert_rows,
            conflict_keys=["player_id", "game_date"],
        )
    return len(upsert_rows)


def run() -> dict:
    today = now_eastern().date()
    db = SessionLocal()
    total = 0
    try:
        for offset in range(1, LOOKBACK_DAYS + 1):
            target = today - timedelta(days=offset)
            total += _process_day(db, target)
        db.commit()
        return {"status": "ok", "rows_written": total}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
