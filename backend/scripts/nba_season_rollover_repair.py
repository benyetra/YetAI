#!/usr/bin/env python3
"""NBA 2026-27 season rollover: verify and repair player data in production.

Subcommands (all read-only unless --apply is passed):

  verify
      pred_team_roster vs ESPN's live rosters (missing players, wrong teams,
      synthetic ids), offseason rows left in pred_recent_games, and leftover
      rows under the ids the old MANUAL_PLAYER_IDS table misassigned.

  purge-offseason [--years 2025,2026] [--apply]
      Delete pred_recent_games rows dated in a Summer League / preseason
      window (July 1 → day before opening night). Those games inflate or
      deflate every rolling average the models read.

  rebuild-misattributed [--seasons 2025,2026] [--apply]
      The old MANUAL_PLAYER_IDS table filed 11 players' box scores under other
      real players' NBA.com ids (e.g. Scoot Henderson under Brandon Miller).
      Rows carry no player name, so they can't be untangled: delete every
      pred_recent_games / pred_player_career_data row for the affected ids and
      re-pull those players' games from API-Sports (~100 API calls). Also
      relabels rows the old resolver filed under a retired namesake's id.

Usage:
  cd backend
  PYTHONPATH=. .venv/bin/python scripts/nba_season_rollover_repair.py verify
  PYTHONPATH=. .venv/bin/python scripts/nba_season_rollover_repair.py purge-offseason
  PYTHONPATH=. .venv/bin/python scripts/nba_season_rollover_repair.py purge-offseason --apply
  PYTHONPATH=. .venv/bin/python scripts/nba_season_rollover_repair.py rebuild-misattributed --apply

Needs DATABASE_URL; rebuild-misattributed also needs NBA_API_KEY.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

from app.core.database import SessionLocal
from app.models.predictions_models import PlayerCareerData, RecentGames, TeamRoster
from app.services.etl.nba._api_sports import (
    API_SPORTS_TO_NBA,
    SYNTHETIC_ID_BASE,
    _get_static_players,
    api_request,
    normalize_player_name,
    resolve_nba_player_id,
)
from app.services.etl.nba._espn import NBA_TEAM_NAMES, fetch_team_rosters
from app.services.etl.nba._season import (
    is_offseason_date,
    offseason_window,
    season_label,
)
from app.services.etl.nba.update_player_career_data import (
    _find_api_player_id,
)
from app.services.etl.nba.update_player_career_data import run as run_career_data
from app.services.etl.nba.update_recent_games import (
    is_nba_league_game,
    stat_line_fields,
)

# The ids the pre-2026-10 MANUAL_PLAYER_IDS table returned for these names.
# Each one is really a different player's NBA.com id.
OLD_BAD_MANUAL_IDS: dict[str, int] = {
    "scoot henderson": 1641706,
    "jaime jaquez": 1641707,
    "brandon miller": 1641710,
    "keyonte george": 1641712,
    "bilal coulibaly": 1641713,
    "dereck lively": 1641714,
    "jordan hawkins": 1641715,
    "jett howard": 1641716,
    "taylor hendricks": 1641717,
    "kobe bufkin": 1641718,
    "cam whitmore": 1631170,
}

# Old resolver picked the first namesake in nba_api's list — a retired player
# whose id has no other games — so these rows can simply be relabelled.
# old id -> correct id
RETIRED_NAMESAKE_REMAPS: dict[int, int] = {
    1585: 1630314,  # Brandon Williams (retired) -> Brandon Williams (active)
}


def affected_players() -> dict[int, str]:
    """NBA.com id -> name for every player whose rows may be mixed: the
    misassigned names themselves plus whoever really owns each bad id."""
    by_id = {p["id"]: p["full_name"] for p in _get_static_players()}
    affected: dict[int, str] = {}
    for name, bad_id in OLD_BAD_MANUAL_IDS.items():
        correct = resolve_nba_player_id(name)
        if correct and correct < SYNTHETIC_ID_BASE:
            affected[correct] = by_id.get(correct, name)
        affected.setdefault(bad_id, by_id.get(bad_id, f"(unknown {bad_id})"))
    return affected


def cmd_verify(db) -> int:
    problems = 0
    roster = db.query(TeamRoster).all()
    print(
        f"pred_team_roster: {len(roster)} players on "
        f"{len({r.team_id for r in roster})} teams"
    )
    synthetic = [r for r in roster if r.player_id >= SYNTHETIC_ID_BASE]
    print(f"  synthetic ids (no NBA.com id yet): {len(synthetic)}")
    for r in sorted(synthetic, key=lambda r: r.player_name)[:40]:
        print(f"    {r.player_name} ({NBA_TEAM_NAMES.get(r.team_id, r.team_id)})")

    espn = fetch_team_rosters()
    print(f"ESPN rosters fetched: {len(espn)}/30 teams")
    if espn:
        ours = {normalize_player_name(r.player_name): r.team_id for r in roster}
        missing, wrong_team = [], []
        for team_id, names in espn.items():
            for name in names:
                key = normalize_player_name(name)
                if key not in ours:
                    missing.append((NBA_TEAM_NAMES.get(team_id), name))
                elif ours[key] != team_id:
                    wrong_team.append(
                        (
                            name,
                            NBA_TEAM_NAMES.get(ours[key]),
                            NBA_TEAM_NAMES.get(team_id),
                        )
                    )
        print(f"  ESPN players missing from pred_team_roster: {len(missing)}")
        for team, name in sorted(missing):
            print(f"    {team}: {name}")
        print(f"  players on the wrong team (ours -> ESPN): {len(wrong_team)}")
        for row in sorted(wrong_team):
            print(f"    {row[0]}: {row[1]} -> {row[2]}")
        problems += len(missing) + len(wrong_team)

    for year in (2025, 2026):
        first, last = offseason_window(year)
        n = (
            db.query(RecentGames)
            .filter(RecentGames.game_date >= first, RecentGames.game_date <= last)
            .count()
        )
        print(f"pred_recent_games rows in {year} offseason ({first}..{last}): {n}")
        problems += n

    affected = affected_players()
    n = db.query(RecentGames).filter(RecentGames.player_id.in_(affected)).count()
    print(
        f"pred_recent_games rows under misattributed ids: {n} "
        f"({len(affected)} players — run rebuild-misattributed once)"
    )

    latest = (
        db.query(RecentGames.game_date).order_by(RecentGames.game_date.desc()).first()
    )
    print(f"latest pred_recent_games date: {latest[0] if latest else None}")
    return 1 if problems else 0


def cmd_purge_offseason(db, years: list[int], apply: bool) -> int:
    total = 0
    for year in years:
        first, last = offseason_window(year)
        q = db.query(RecentGames).filter(
            RecentGames.game_date >= first, RecentGames.game_date <= last
        )
        n = q.count()
        total += n
        print(f"{year} offseason {first}..{last}: {n} rows")
        if apply and n:
            q.delete(synchronize_session=False)
    if apply:
        db.commit()
        print(f"deleted {total} rows")
    else:
        print(f"dry run — would delete {total} rows (pass --apply)")
    return 0


def _season_game_index(season: int) -> dict[int, dict]:
    """API-Sports game id -> game for every NBA team's schedule that season."""
    index: dict[int, dict] = {}
    for api_team_id in sorted(set(API_SPORTS_TO_NBA)):
        data = api_request("games", params={"season": season, "team": api_team_id})
        for game in (data or {}).get("response") or []:
            index[game["id"]] = game
        time.sleep(0.2)
    return index


def _game_date(game: dict) -> date | None:
    start = (game.get("date") or {}).get("start")
    return date.fromisoformat(start[:10]) if start else None


def cmd_rebuild(db, seasons: list[int], apply: bool) -> int:
    affected = affected_players()
    ids = list(affected)
    rg = db.query(RecentGames).filter(RecentGames.player_id.in_(ids)).count()
    labels = [season_label(s) for s in seasons]
    cd = (
        db.query(PlayerCareerData)
        .filter(
            PlayerCareerData.player_id.in_(ids), PlayerCareerData.season.in_(labels)
        )
        .count()
    )
    for old_id, new_id in RETIRED_NAMESAKE_REMAPS.items():
        n = db.query(RecentGames).filter(RecentGames.player_id == old_id).count()
        print(f"relabel {n} pred_recent_games rows {old_id} -> {new_id}")
        if apply and n:
            clash = {
                d
                for (d,) in db.query(RecentGames.game_date).filter(
                    RecentGames.player_id == new_id
                )
            }
            for row in db.query(RecentGames).filter(RecentGames.player_id == old_id):
                if row.game_date in clash:
                    db.delete(row)
                else:
                    row.player_id = new_id
            db.query(PlayerCareerData).filter(
                PlayerCareerData.player_id == old_id
            ).delete(synchronize_session=False)
            db.commit()

    print("affected players:")
    for pid, name in sorted(affected.items(), key=lambda kv: kv[1]):
        print(f"  {pid}  {name}")
    print(f"would delete {rg} pred_recent_games and {cd} pred_player_career_data rows")
    if not apply:
        print("dry run — pass --apply to delete and re-pull from API-Sports")
        return 0

    db.query(RecentGames).filter(RecentGames.player_id.in_(ids)).delete(
        synchronize_session=False
    )
    db.query(PlayerCareerData).filter(
        PlayerCareerData.player_id.in_(ids), PlayerCareerData.season.in_(labels)
    ).delete(synchronize_session=False)
    db.commit()

    rebuildable = {
        pid: name for pid, name in affected.items() if not name.startswith("(unknown")
    }
    for season in seasons:
        print(f"season {season}: indexing schedules…")
        games = _season_game_index(season)
        added = 0
        for pid, name in rebuildable.items():
            api_id = _find_api_player_id(name)
            if not api_id:
                print(f"  {name}: no API-Sports id, skipped")
                continue
            data = api_request(
                "players/statistics", params={"id": api_id, "season": season}
            )
            for line in (data or {}).get("response") or []:
                game = games.get((line.get("game") or {}).get("id"))
                if not game or not is_nba_league_game(game):
                    continue
                game_date = _game_date(game)
                if not game_date or is_offseason_date(game_date):
                    continue
                fields = stat_line_fields(
                    line,
                    (game.get("teams", {}).get("home") or {}).get("id"),
                    (game.get("teams", {}).get("visitors") or {}).get("id"),
                )
                existing = (
                    db.query(RecentGames)
                    .filter_by(player_id=pid, game_date=game_date)
                    .first()
                )
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                else:
                    db.add(RecentGames(player_id=pid, game_date=game_date, **fields))
                    added += 1
            db.commit()
            time.sleep(0.2)
        print(f"  added {added} games")
        result = run_career_data(season=season, players=list(rebuildable.items()))
        print(f"  career data: {result}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    purge = sub.add_parser("purge-offseason")
    purge.add_argument("--years", default="2025,2026")
    purge.add_argument("--apply", action="store_true")
    rebuild = sub.add_parser("rebuild-misattributed")
    rebuild.add_argument("--seasons", default="2025,2026")
    rebuild.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if SessionLocal is None:
        print("ERROR: database not configured")
        return 1
    db = SessionLocal()
    try:
        if args.cmd == "verify":
            return cmd_verify(db)
        if args.cmd == "purge-offseason":
            years = [int(y) for y in args.years.split(",")]
            return cmd_purge_offseason(db, years, args.apply)
        seasons = [int(s) for s in args.seasons.split(",")]
        return cmd_rebuild(db, seasons, args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
