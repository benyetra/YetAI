"""Rows that must not change once a game starts, and scratches before tip."""

from __future__ import annotations

from datetime import date, datetime

from app.models.predictions_models import NBAGameLines, TodayActivePlayers
from app.services.etl._game_start import has_started

OUT = "OUT"  # fanduel_over_under marker: ruled out, row kept as last shown


def active_players_not_started(db, today: date, *, now: datetime | None = None) -> list:
    """Today's TodayActivePlayers whose game has not started.

    Start comes from NBAGameLines.game_time (naive UTC), joined by game date and
    team names; no game line -> game_date only (fail-safe: a started player's
    row is never rewritten, an unknown start keeps today's board fresh).
    """
    starts: dict[frozenset, datetime | None] = {}
    for g in db.query(NBAGameLines).filter(NBAGameLines.game_date == today).all():
        starts[frozenset((g.home_team_name, g.away_team_name))] = g.game_time
    players = (
        db.query(TodayActivePlayers).filter(TodayActivePlayers.game_date == today).all()
    )
    return [
        p
        for p in players
        if not has_started(
            starts.get(frozenset((p.team_name, p.opponent_team_name))),
            game_date=today,
            now=now,
        )
    ]


def mark_projection_out(db, model, today: date, player_id: int) -> bool:
    """Flag ``player_id``'s row for ``today`` as ruled out; never delete it.

    A row users saw keeps its line, price and projection. ``fanduel_over_under``
    = "OUT" keeps the auto-picker off him; a later refresh that finds him
    active again restores the side (see apply_fanduel_to_projection). Tables
    without that column are left as is.
    """
    if not hasattr(model, "fanduel_over_under"):
        return False
    marked = (
        db.query(model)
        .filter(
            model.date == today,
            model.player_id == player_id,
            model.fanduel_line.isnot(None),
        )
        .update({"fanduel_over_under": OUT}, synchronize_session=False)
    )
    if marked:
        db.commit()
    return bool(marked)
