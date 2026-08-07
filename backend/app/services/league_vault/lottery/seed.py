"""Build lottery seeding from a finished season's standings / playoff finish."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.league_vault_models import LvManager, LvMatchup, LvSeason, LvTeam
from app.services.league_vault.lottery.odds import (
    LOTTERY_PICKS,
    combinations_for_field,
    odds_pct,
)


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "manager"


def _playoff_team_ids(db: Session, season: LvSeason, teams: list[LvTeam]) -> set[int]:
    """Teams that made the playoffs (matchups, seed, or top-N final_rank)."""
    ids: set[int] = set()
    playoff_n = season.playoff_teams
    for t in teams:
        if t.playoff_seed is not None and t.playoff_seed > 0:
            ids.add(t.id)
        if playoff_n and t.final_rank is not None and t.final_rank <= playoff_n:
            ids.add(t.id)

    matchups = db.query(LvMatchup).filter_by(season_id=season.id, is_playoff=True).all()
    for m in matchups:
        if m.team_a_id:
            ids.add(m.team_a_id)
        if m.team_b_id:
            ids.add(m.team_b_id)

    for mid in (season.champion_manager_id, season.runner_up_manager_id):
        if mid is None:
            continue
        for t in teams:
            if t.manager_id == mid:
                ids.add(t.id)

    if playoff_n and len(ids) < playoff_n:
        ranked = sorted(
            [t for t in teams if t.final_rank is not None],
            key=lambda t: t.final_rank or 999,
        )
        for t in ranked[:playoff_n]:
            ids.add(t.id)

    return ids


def _sort_key_worst_first(team: LvTeam) -> tuple:
    rank = team.final_rank if team.final_rank is not None else -1
    wins = team.wins if team.wins is not None else 0
    pf = team.points_for if team.points_for is not None else 0.0
    return (-rank if rank > 0 else 0, wins, pf, team.id)


def _sort_key_playoff_finish(team: LvTeam, season: LvSeason) -> tuple:
    """Best finish first (champ → … → earliest exit)."""
    if season.champion_manager_id and team.manager_id == season.champion_manager_id:
        return (0, 0, team.id)
    if season.runner_up_manager_id and team.manager_id == season.runner_up_manager_id:
        return (1, 0, team.id)
    rank = team.final_rank if team.final_rank is not None else 999
    seed = team.playoff_seed if team.playoff_seed is not None else 99
    return (2, rank, seed, team.id)


def _entry(
    team: LvTeam,
    manager: LvManager | None,
    *,
    group: str,
    seed_slot: int,
    combinations: int | None = None,
    chance_pct: float | None = None,
) -> dict[str, Any]:
    display = "Unknown"
    slug = None
    if manager:
        display = manager.display_name or manager.canonical_name or "Unknown"
        slug = _slugify(display)
    return {
        "team_id": team.id,
        "team_name": team.team_name,
        "manager_id": team.manager_id,
        "manager_slug": slug,
        "display_name": display,
        "final_rank": team.final_rank,
        "playoff_seed": team.playoff_seed,
        "wins": team.wins,
        "losses": team.losses,
        "points_for": team.points_for,
        "group": group,
        "seed_slot": seed_slot,
        "combinations": combinations,
        "chance_pct": chance_pct,
    }


def build_seed_snapshot(db: Session, season: LvSeason) -> dict[str, Any]:
    """
    Lottery field = non-playoff teams, worst → best (classic NBA).
    Playoff block = reverse playoff finish (earliest exit drafts first among
    playoff teams; champion last overall).
    """
    teams = db.query(LvTeam).filter_by(season_id=season.id).all()
    if not teams:
        raise ValueError(f"No teams for season {season.season}")

    managers = {
        m.id: m
        for m in db.query(LvManager).filter_by(lineage_id=season.lineage_id).all()
    }

    playoff_ids = _playoff_team_ids(db, season, teams)
    lottery_teams = [t for t in teams if t.id not in playoff_ids]
    playoff_teams = [t for t in teams if t.id in playoff_ids]

    lottery_teams.sort(key=_sort_key_worst_first)
    playoff_teams.sort(key=lambda t: _sort_key_playoff_finish(t, season))

    combos = combinations_for_field(len(lottery_teams))
    pcts = odds_pct(combos)

    lottery_entries = [
        _entry(
            t,
            managers.get(t.manager_id),
            group="lottery",
            seed_slot=i + 1,
            combinations=combos[i],
            chance_pct=pcts[i],
        )
        for i, t in enumerate(lottery_teams)
    ]
    playoff_rev = list(reversed(playoff_teams))
    playoff_entries = [
        _entry(
            t,
            managers.get(t.manager_id),
            group="playoff",
            seed_slot=i + 1,
        )
        for i, t in enumerate(playoff_rev)
    ]

    return {
        "source_season": season.season,
        "playoff_teams_setting": season.playoff_teams,
        "lottery_picks": LOTTERY_PICKS,
        "odds_system": "nba_classic_1994_2018",
        "odds_note": (
            "Classic NBA ping-pong lottery: weighted draw for picks 1–3 among "
            "non-playoff teams; remaining lottery slots keep reverse standings; "
            "playoff teams follow in reverse playoff finish (champion last)."
        ),
        "lottery_field": lottery_entries,
        "playoff_block": playoff_entries,
    }
