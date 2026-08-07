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


def _playoff_team_ids(season: LvSeason, teams: list[LvTeam]) -> set[int]:
    """
    Teams that made the winners' bracket / championship path.

    Prefer explicit playoff seeds. Otherwise take the top N by regular-season
    standing (final_rank). Do **not** treat every is_playoff week matchup as
    membership — consolation / toilet-bowl games include the whole league.
    """
    playoff_n = season.playoff_teams
    seeded = [
        t
        for t in teams
        if t.playoff_seed is not None
        and t.playoff_seed > 0
        and (not playoff_n or t.playoff_seed <= playoff_n)
    ]
    if seeded:
        seeded_sorted = sorted(seeded, key=lambda t: t.playoff_seed or 999)
        if playoff_n:
            return {t.id for t in seeded_sorted[:playoff_n]}
        return {t.id for t in seeded_sorted}

    if playoff_n:
        ranked = sorted(
            [t for t in teams if t.final_rank is not None],
            key=lambda t: t.final_rank or 999,
        )
        if ranked:
            return {t.id for t in ranked[:playoff_n]}

    # Last resort: champion + runner-up only (better than marking everyone)
    ids: set[int] = set()
    for mid in (season.champion_manager_id, season.runner_up_manager_id):
        if mid is None:
            continue
        for t in teams:
            if t.manager_id == mid:
                ids.add(t.id)
    return ids


def _regular_season_sort_key(team: LvTeam) -> tuple:
    """Best regular-season standing first (low final_rank, then wins/PF)."""
    rank = team.final_rank if team.final_rank is not None else 999
    wins = team.wins if team.wins is not None else 0
    pf = team.points_for if team.points_for is not None else 0.0
    return (rank, -wins, -pf, team.id)


def _sort_key_worst_first(team: LvTeam) -> tuple:
    rank = team.final_rank if team.final_rank is not None else -1
    wins = team.wins if team.wins is not None else 0
    pf = team.points_for if team.points_for is not None else 0.0
    return (-rank if rank > 0 else 0, wins, pf, team.id)


def _loser_id(matchup: LvMatchup) -> int | None:
    if not matchup.winner_team_id:
        return None
    if matchup.winner_team_id == matchup.team_a_id:
        return matchup.team_b_id
    if matchup.winner_team_id == matchup.team_b_id:
        return matchup.team_a_id
    return None


def _playoff_finish_places(
    db: Session,
    season: LvSeason,
    playoff_teams: list[LvTeam],
) -> dict[int, int]:
    """
    Map team_id → playoff finish place (1 = champion, higher = earlier exit).

    Uses winners-bracket place games when present (`playoff_round` holds Sleeper
    `p`: 1=title, 3=3rd, 5=5th). Otherwise walks playoff matchups **among the
    playoff field only** from latest week backward so consolation/toilet-bowl
    games (non-playoff opponents) never pollute places. Regular-season
    final_rank / playoff_seed are only a last-resort fallback.
    """
    if not playoff_teams:
        return {}

    by_id = {t.id: t for t in playoff_teams}
    places: dict[int, int] = {}

    matchups = db.query(LvMatchup).filter_by(season_id=season.id, is_playoff=True).all()
    po_matchups = [
        m
        for m in matchups
        if m.team_a_id in by_id
        and m.team_b_id in by_id
        and m.winner_team_id
        and m.team_a_id != m.team_b_id
    ]

    # Sleeper winners bracket: playoff_round stores place contested (p).
    for m in po_matchups:
        if m.bracket != "winners" or not m.playoff_round:
            continue
        p = int(m.playoff_round)
        if p < 1:
            continue
        loser = _loser_id(m)
        if m.winner_team_id in by_id:
            places[m.winner_team_id] = p
        if loser is not None and loser in by_id:
            places[loser] = p + 1

    # Anchor from season champ / runner when bracket places missing.
    for t in playoff_teams:
        if season.champion_manager_id and t.manager_id == season.champion_manager_id:
            places.setdefault(t.id, 1)
        elif (
            season.runner_up_manager_id and t.manager_id == season.runner_up_manager_id
        ):
            places.setdefault(t.id, 2)

    unplaced = {t.id for t in playoff_teams if t.id not in places}
    while unplaced:
        candidates = [
            m
            for m in po_matchups
            if m.team_a_id in unplaced and m.team_b_id in unplaced
        ]
        if not candidates:
            break
        m = max(
            candidates,
            key=lambda x: (x.week or 0, x.playoff_round or 0, x.id or 0),
        )
        next_place = max(places.values(), default=0) + 1
        loser = _loser_id(m)
        if m.winner_team_id in unplaced:
            places[m.winner_team_id] = next_place
            unplaced.discard(m.winner_team_id)
        if loser is not None and loser in unplaced:
            places[loser] = next_place + 1
            unplaced.discard(loser)

    # Remaining (byes / incomplete bracket): worse regular-season standing =
    # worse playoff finish among leftovers.
    if unplaced:
        leftovers = sorted(
            [by_id[i] for i in unplaced],
            key=_regular_season_sort_key,
            reverse=True,
        )
        next_place = max(places.values(), default=0)
        for t in leftovers:
            next_place += 1
            places[t.id] = next_place

    return places


def _entry(
    team: LvTeam,
    manager: LvManager | None,
    *,
    group: str,
    seed_slot: int,
    combinations: int | None = None,
    chance_pct: float | None = None,
    playoff_finish: int | None = None,
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
        "playoff_finish": playoff_finish,
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
    Playoff block = reverse playoff **results** (earliest exit drafts first among
    playoff teams; champion last overall) — not regular-season seeds.
    """
    teams = db.query(LvTeam).filter_by(season_id=season.id).all()
    if not teams:
        raise ValueError(f"No teams for season {season.season}")

    managers = {
        m.id: m
        for m in db.query(LvManager).filter_by(lineage_id=season.lineage_id).all()
    }

    playoff_ids = _playoff_team_ids(season, teams)
    lottery_teams = [t for t in teams if t.id not in playoff_ids]
    playoff_teams = [t for t in teams if t.id in playoff_ids]

    lottery_teams.sort(key=_sort_key_worst_first)
    finish_places = _playoff_finish_places(db, season, playoff_teams)
    playoff_teams.sort(
        key=lambda t: (
            finish_places.get(t.id, 999),
            t.final_rank if t.final_rank is not None else 999,
            t.id,
        )
    )

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
    # Reverse playoff finish → earliest exit first, champion last.
    playoff_rev = list(reversed(playoff_teams))
    playoff_entries = [
        _entry(
            t,
            managers.get(t.manager_id),
            group="playoff",
            seed_slot=i + 1,
            playoff_finish=finish_places.get(t.id),
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
