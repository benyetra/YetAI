#!/usr/bin/env python3
"""Collect the NHL season's games and rebuild team, goalie and skater stats (YetAI-5p8).

Why: pred_nhl_game_stats stopped at 20 games per team, team stats were built from
preseason games only, goalie stats summed every season and skater stats held 50 of
~770 players. This runs the fixed collectors once for a whole season:

  1. collect every finished regular-season/playoff game not yet stored (box scores;
     also writes starter goalie actuals), for --season and, with --with-previous, the
     season before (the shrinkage prior; production holds only 329 of its 1312 games);
  2. rebuild pred_nhl_goalies, pred_nhl_team_stats and pred_nhl_players for --season;
  3. check team games played against the league standings (--check-standings).

This writes starter goalie actuals only. Relief appearances (10+ minutes) come from
scripts/nhl_recollect_actuals.py: run it after this one for the season's dates, then
run this script with --apply once more (no new games, about 70 calls) so goalie
games_played counts them. The 05:00 ET pipeline also rebuilds goalie stats daily.

Dry run is the default: everything runs inside one transaction that is rolled back
(commits become flushes). Pass --apply to write. Idempotent: a second --apply fetches
no box scores and rewrites the same stats.

Usage:
  cd backend
  export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
  PYTHONPATH=. python3 scripts/nhl_backfill_season.py --with-previous --check-standings 2026-11-13
  PYTHONPATH=. python3 scripts/nhl_backfill_season.py --with-previous --check-standings 2026-11-13 --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from sqlalchemy import func

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _counts(db, season):
    from app.models.predictions_models import (
        NHLGameStats,
        NHLGoalie,
        NHLGoalieActuals,
        NHLPlayer,
        NHLTeamStats,
    )

    games = dict(
        db.query(NHLGameStats.season, func.count())
        .filter(NHLGameStats.game_type == 2)
        .group_by(NHLGameStats.season)
        .all()
    )
    start = season // 10000 * 1_000_000 + 20_000
    return {
        "regular_games_this_season": games.get(season, 0),
        "regular_games_previous_season": games.get(season - 10001, 0),
        "goalie_actuals_this_season": db.query(NHLGoalieActuals)
        .filter(NHLGoalieActuals.game_id >= start, NHLGoalieActuals.game_id < start + 10_000)
        .count(),  # fmt: skip
        "teams_with_games": db.query(NHLTeamStats)
        .filter(NHLTeamStats.games_played > 0)
        .count(),
        "skaters_with_games": db.query(NHLPlayer)
        .filter(NHLPlayer.games_played > 0)
        .count(),
        "goalies_with_games": db.query(NHLGoalie)
        .filter(NHLGoalie.games_played > 0)
        .count(),
        "goalies_with_last_game_date": db.query(NHLGoalie)
        .filter(NHLGoalie.last_game_date.isnot(None))
        .count(),
        "max_goalie_games_played": db.query(func.max(NHLGoalie.games_played)).scalar(),
    }


def _check_standings(db, day: str) -> int:
    """Rows whose games_played differs from the standings on ``day`` (0 = all match)."""
    import requests

    from app.models.predictions_models import NHLTeamStats

    data = requests.get(
        f"https://api-web.nhle.com/v1/standings/{day}", timeout=20
    ).json()
    abbrev_ids = {}
    from app.services.etl.nhl.collect_historical_data import NHL_TEAMS

    for abbrev, info in NHL_TEAMS.items():
        abbrev_ids[abbrev] = info["id"]
    ours = {t.team_id: t.games_played for t in db.query(NHLTeamStats).all()}
    bad = 0
    for row in data["standings"]:
        abbrev = row["teamAbbrev"]["default"]
        tid = abbrev_ids.get(abbrev)
        mine = ours.get(tid)
        if mine != row["gamesPlayed"]:
            bad += 1
            logger.warning(
                "standings mismatch %s (id %s): ours %s, league %s",
                abbrev,
                tid,
                mine,
                row["gamesPlayed"],
            )
    logger.info(
        "standings check %s: %d of %d teams match",
        day,
        len(data["standings"]) - bad,
        len(data["standings"]),
    )
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, help="Season id (default: current)")
    parser.add_argument(
        "--with-previous",
        action="store_true",
        help="Also collect the previous season's games (the shrinkage prior)",
    )
    parser.add_argument(
        "--check-standings",
        metavar="YYYY-MM-DD",
        help="Compare team games played with the standings on this date",
    )
    parser.add_argument("--apply", action="store_true", help="Write (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry run")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    from app.services.etl.nhl import collect_historical_data as chd
    from app.services.etl.nhl import nhl_api_client
    from app.services.etl.nhl._config import _resolve_season
    from app.services.etl.nhl._db import close_session, init_session

    season = _resolve_season(args.season)
    calls = {"n": 0}
    real_get = nhl_api_client.requests.get

    def counting_get(*a, **kw):
        calls["n"] += 1
        return real_get(*a, **kw)

    nhl_api_client.requests.get = counting_get
    db = init_session()
    if not args.apply:
        db.commit = db.flush  # one transaction, rolled back below
    mode = "APPLY" if args.apply else "DRY RUN"
    logger.info("NHL season backfill %s (%s)", season, mode)
    logger.info("before: %s", _counts(db, season))
    t0 = time.monotonic()
    try:
        seasons = [season - 10001, season] if args.with_previous else [season]
        for s in seasons:
            n = chd.collect_game_data(season=s)
            logger.info("season %s: %d new games collected", s, n)
        chd.populate_teams()
        chd.calculate_goalie_stats(season)
        chd.calculate_team_stats(season)
        chd.collect_team_offensive_stats(season)
        chd.collect_season_player_stats(season)
        db.flush()
        logger.info("after: %s", _counts(db, season))
        bad = _check_standings(db, args.check_standings) if args.check_standings else 0
        logger.info(
            "elapsed %.0fs, NHL API calls %d", time.monotonic() - t0, calls["n"]
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
            logger.info("Dry run only; re-run with --apply to write.")
    finally:
        nhl_api_client.requests.get = real_get
        close_session()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
