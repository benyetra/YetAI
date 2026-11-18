"""Who is missing from the player's team, and how much of the team's work they carry.

Used by BOTH the training dataset and tonight's serving path (through
`build_features`), so a feature means the same thing in both.

Teammates of player P in a game are the other players' rows with the same
`game_date` and `opponent_team_id` (`RecentGames` has no team column, and only
one team plays a given opponent on a given day).

The team window is P's last ROTATION_GAMES games (minutes > 0) before the game
date. A rotation teammate averages ROTATION_MIN_MINUTES or more over it. For each
rotation teammate, `weight` says how unavailable he is for the target game, and
each `team_out_*_share` is the sum of weight x his share of the team's total in
that window. Where the weight comes from:
* past game (P has a box row for the date): 1 if the teammate has no minutes
  that day, else 0. Only presence is read, never a stat of the target game.
* tonight (no box row yet): the active-players list and the injury table.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, or_

from app.models.predictions_models import (
    PlayerInjuryStatus,
    RecentGames,
    TodayActivePlayers,
)
from app.services.etl.nba._samples import player_games

ROTATION_GAMES = 10
ROTATION_MIN_MINUTES = 10.0
DOUBTFUL_WEIGHT = 0.75
RETURN_GAP_DAYS = 10
SHARE_STATS = {
    "min": "minutes",
    "fga": "fg_attempts",
    "reb": "rebounds",
    "ast": "assists",
}

_OUT = {"out", "ir"}


def _zeros() -> dict:
    out = {f"team_out_{k}_share": 0.0 for k in SHARE_STATS}
    out["team_out_rotation_players"] = 0.0
    out.update({f"own_{k}_share": 0.0 for k in SHARE_STATS})
    return out


def _box_weights(db, game_date: date, opponent_team_id: int, ids) -> dict:
    played = {
        pid
        for (pid,) in db.query(RecentGames.player_id).filter(
            RecentGames.game_date == game_date,
            RecentGames.opponent_team_id == opponent_team_id,
            RecentGames.minutes > 0,
            RecentGames.player_id.in_(ids),
        )
    }
    return {pid: 0.0 if pid in played else 1.0 for pid in ids}


def _status_weights(db, player_id: int, game_date: date, ids) -> dict:
    me = (
        db.query(TodayActivePlayers)
        .filter_by(player_id=player_id, game_date=game_date)
        .first()
    )
    if me is None:  # no information
        return {pid: 0.0 for pid in ids}
    active = {
        pid
        for (pid,) in db.query(TodayActivePlayers.player_id).filter_by(
            team_id=me.team_id, game_date=game_date
        )
    }
    status = dict(
        db.query(PlayerInjuryStatus.player_id, PlayerInjuryStatus.status).filter(
            PlayerInjuryStatus.player_id.in_(ids)
        )
    )
    weights = {}
    for pid in ids:
        s = (status.get(pid) or "").lower()
        if pid not in active or s in _OUT:
            weights[pid] = 1.0
        elif s == "doubtful":
            weights[pid] = DOUBTFUL_WEIGHT
        else:
            weights[pid] = 0.0
    return weights


def team_context(
    db,
    player_id: int,
    game_date: date,
    opponent_team_id: int,
    source: str | None = None,
) -> dict:
    """Team-availability and role-share features. `source`: "box", "status" or
    None (box when the player has a row for `game_date`, else status)."""
    out = _zeros()
    window = player_games(
        db, player_id, game_date, ROTATION_GAMES, RecentGames.minutes > 0
    )
    if not window:
        return out

    pairs = {(g.game_date, g.opponent_team_id) for g in window}
    rows = (
        db.query(RecentGames)
        .filter(
            or_(
                *[
                    and_(RecentGames.game_date == d, RecentGames.opponent_team_id == o)
                    for d, o in pairs
                ]
            )
        )
        .all()
    )
    team = {k: 0.0 for k in SHARE_STATS}
    by_player: dict[int, dict] = {}
    for r in rows:
        sums = by_player.setdefault(r.player_id, {k: 0.0 for k in SHARE_STATS})
        for k, col in SHARE_STATS.items():
            v = getattr(r, col) or 0.0
            sums[k] += v
            team[k] += v

    def share(pid: int, k: str) -> float:
        return by_player[pid][k] / team[k] if team[k] else 0.0

    for k in SHARE_STATS:
        out[f"own_{k}_share"] = share(player_id, k) if player_id in by_player else 0.0

    n = len(window)
    rotation = [
        pid
        for pid, s in by_player.items()
        if pid != player_id and s["min"] / n >= ROTATION_MIN_MINUTES
    ]
    if not rotation:
        return out

    if source is None:
        has_box = (
            db.query(RecentGames.id)
            .filter_by(player_id=player_id, game_date=game_date)
            .first()
            is not None
        )
        source = "box" if has_box else "status"
    if source == "box":
        weights = _box_weights(db, game_date, opponent_team_id, rotation)
    else:
        weights = _status_weights(db, player_id, game_date, rotation)

    for pid in rotation:
        for k in SHARE_STATS:
            out[f"team_out_{k}_share"] += weights[pid] * share(pid, k)
    out["team_out_rotation_players"] = sum(weights.values())
    return out
