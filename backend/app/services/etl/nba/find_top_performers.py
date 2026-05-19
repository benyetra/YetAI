"""Identify per-matchup top projected performers across today's stat tables.

Port of YetiBets/scripts/nba/find_top_performers.py — but simplified to read
directly from today's projection tables instead of recomputing weighted
career/recent averages and applying opponent-defense adjustments. By the time
this task runs, every per-stat generator has already done that math, so this
job just picks the argmax projection per (matchup, stat).

Flow:
  1. Get today's date (Eastern).
  2. From TodayActivePlayers, build the unique set of matchups for today
     (one row per pair of teams).
  3. For each matchup, for each tracked stat (points, assists, rebounds,
     three_pt_made), find the player from either side with the highest
     projected value and record their name.
  4. Upsert into pred_top_performers (matchup is the unique key).
  5. Return a dict with the same data so the caller can render it directly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.predictions_models import (
    AssistsProjections,
    PointsProjections,
    ReboundsProjections,
    ThreePointProjections,
    TodayActivePlayers,
    TopPerformers,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)


# (stat key in result dict, projection model, projected-value attribute)
STAT_SOURCES: list[tuple[str, Any, str]] = [
    ("points", PointsProjections, "projected_points"),
    ("assists", AssistsProjections, "projected_assists"),
    ("rebounds", ReboundsProjections, "projected_rebounds"),
    ("three_pt_made", ThreePointProjections, "projected_three_pt_made"),
]


def _unique_matchups(db: Session, today) -> list[tuple[int, str, int, str]]:
    """Return list of (team_a_id, team_a_name, team_b_id, team_b_name) tuples.

    Each matchup appears exactly once even though TodayActivePlayers has rows
    on both sides — we canonicalize by min(team_id) so order is deterministic.
    """
    rows = (
        db.query(
            TodayActivePlayers.team_id,
            TodayActivePlayers.team_name,
            TodayActivePlayers.opponent_team_id,
            TodayActivePlayers.opponent_team_name,
        )
        .filter(TodayActivePlayers.game_date == today)
        .distinct()
        .all()
    )

    seen: set[tuple[int, int]] = set()
    matchups: list[tuple[int, str, int, str]] = []
    for team_id, team_name, opp_id, opp_name in rows:
        if team_id is None or opp_id is None:
            continue
        if team_id <= opp_id:
            key = (team_id, opp_id)
            ordered = (team_id, team_name, opp_id, opp_name)
        else:
            key = (opp_id, team_id)
            ordered = (opp_id, opp_name, team_id, team_name)
        if key in seen:
            continue
        seen.add(key)
        matchups.append(ordered)
    return matchups


def _player_ids_for_teams(db: Session, today, team_a: int, team_b: int) -> set[int]:
    rows = (
        db.query(TodayActivePlayers.player_id)
        .filter(
            TodayActivePlayers.game_date == today,
            TodayActivePlayers.team_id.in_([team_a, team_b]),
        )
        .all()
    )
    return {pid for (pid,) in rows}


def _top_for_stat(
    db: Session, today, player_ids: set[int], model, projected_attr: str
) -> tuple[str | None, float | None, int | None]:
    """Return (player_name, projected_value, player_id) for the top projection
    among `player_ids` for the given stat. None if no projections exist."""
    if not player_ids:
        return None, None, None
    proj_col = getattr(model, projected_attr)
    row = (
        db.query(model)
        .filter(
            model.date == today,
            model.player_id.in_(player_ids),
            proj_col.isnot(None),
        )
        .order_by(proj_col.desc())
        .first()
    )
    if row is None:
        return None, None, None
    value = getattr(row, projected_attr, None)
    return (
        row.player_name,
        float(value) if value is not None else None,
        row.player_id,
    )


def run() -> dict:
    today = now_eastern().date()
    db = SessionLocal()
    try:
        matchups = _unique_matchups(db, today)
        if not matchups:
            logger.info("find_top_performers: no matchups for %s", today)
            return {
                "status": "ok",
                "date": today.isoformat(),
                "matchups": [],
                "matchup_count": 0,
            }

        results: list[dict[str, Any]] = []
        written = 0
        updated = 0

        for team_a_id, team_a_name, team_b_id, team_b_name in matchups:
            matchup_str = f"{team_a_name} vs {team_b_name}"
            player_ids = _player_ids_for_teams(db, today, team_a_id, team_b_id)

            per_stat: dict[str, dict[str, Any]] = {}
            for stat_key, model, projected_attr in STAT_SOURCES:
                name, value, pid = _top_for_stat(
                    db, today, player_ids, model, projected_attr
                )
                per_stat[stat_key] = {
                    "player_name": name,
                    "player_id": pid,
                    "projected_value": value,
                }

            try:
                existing = (
                    db.query(TopPerformers)
                    .filter(TopPerformers.matchup == matchup_str)
                    .first()
                )
                if existing:
                    existing.game_date = today
                    existing.top_scorer = per_stat["points"]["player_name"]
                    existing.top_assist = per_stat["assists"]["player_name"]
                    existing.top_rebound = per_stat["rebounds"]["player_name"]
                    existing.top_three_pt = per_stat["three_pt_made"]["player_name"]
                    updated += 1
                else:
                    db.add(
                        TopPerformers(
                            game_date=today,
                            matchup=matchup_str,
                            top_scorer=per_stat["points"]["player_name"],
                            top_assist=per_stat["assists"]["player_name"],
                            top_rebound=per_stat["rebounds"]["player_name"],
                            top_three_pt=per_stat["three_pt_made"]["player_name"],
                        )
                    )
                    written += 1
                db.commit()
            except Exception:
                logger.exception(
                    "find_top_performers: failed to persist matchup=%s", matchup_str
                )
                db.rollback()

            results.append({"matchup": matchup_str, "top_performers": per_stat})

        return {
            "status": "ok",
            "date": today.isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "matchup_count": len(matchups),
            "created": written,
            "updated": updated,
            "matchups": results,
        }
    finally:
        db.close()
