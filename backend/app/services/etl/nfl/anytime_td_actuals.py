"""Grade NFL anytime-TD outcomes against predictions."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import NFLAnytimeTDActuals, NFLAnytimeTDPredictions
from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season
from app.services.etl.nfl.team_names import normalize_team_name
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

ANYTIME_TD_CORRECT_THRESHOLD = 0.5
SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})

ACTUALS_UPSERT_UPDATE_KEYS = [
    "game_date",
    "player_name",
    "position",
    "team_name",
    "opponent_team_name",
    "scored_anytime_td",
    "actual_td_count",
    "predicted_td_probability",
    "expected_tds",
    "correct_prediction",
]


def aggregate_player_td_count(stat: dict[str, Any]) -> int:
    """Sum rushing + receiving TDs (anytime TD market excludes passing TDs)."""
    total = 0
    for key in ("rushing_tds", "receiving_tds"):
        value = stat.get(key, 0) or 0
        total += int(value)
    return total


def player_scored_anytime_td(td_count: int) -> bool:
    return td_count >= 1


def grade_correct_prediction(
    *,
    scored: bool,
    td_probability: float | None,
    recommendation: str | None = None,
    threshold: float = ANYTIME_TD_CORRECT_THRESHOLD,
) -> bool | None:
    """Grade binary anytime outcome vs model pick."""
    if recommendation == "OVER":
        return scored
    if recommendation == "NO_PLAY":
        return None
    if td_probability is None:
        return None
    predicted_yes = td_probability >= threshold
    return predicted_yes == scored


def build_actual_upsert_row(
    player_stat: dict[str, Any],
    *,
    season: int,
    week: int,
    prediction: NFLAnytimeTDPredictions | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one ``pred_nfl_anytime_td_actuals`` upsert row."""
    td_count = aggregate_player_td_count(player_stat)
    scored = player_scored_anytime_td(td_count)
    game_date = player_stat.get("game_date")
    if isinstance(game_date, str):
        game_date = date.fromisoformat(game_date)
    if game_date is None:
        game_date = date.today()

    predicted_prob = prediction.td_probability if prediction else None
    expected = prediction.expected_tds if prediction else None
    recommendation = prediction.recommendation if prediction else None

    return {
        "season": season,
        "week": week,
        "game_date": game_date,
        "player_id": str(player_stat["player_id"]),
        "player_name": player_stat["player_name"],
        "position": str(player_stat["position"]).upper(),
        "team_name": normalize_team_name(str(player_stat["team_name"])),
        "opponent_team_name": normalize_team_name(
            str(player_stat["opponent_team_name"])
        ),
        "scored_anytime_td": scored,
        "actual_td_count": td_count,
        "predicted_td_probability": predicted_prob,
        "expected_tds": expected,
        "correct_prediction": grade_correct_prediction(
            scored=scored,
            td_probability=predicted_prob,
            recommendation=recommendation,
        ),
        "created_at": now or datetime.utcnow(),
    }


def _normalize_player_stat(row: dict[str, Any]) -> dict[str, Any] | None:
    position = str(row.get("position", "")).upper()
    if position not in SKILL_POSITIONS:
        return None
    player_id = row.get("player_id")
    if not player_id:
        return None
    return {
        **row,
        "player_id": str(player_id),
        "position": position,
        "team_name": normalize_team_name(str(row.get("team_name", ""))),
        "opponent_team_name": normalize_team_name(
            str(row.get("opponent_team_name", ""))
        ),
    }


def fetch_player_td_stats_nflverse(season: int, week: int) -> list[dict[str, Any]]:
    """Fetch weekly offensive TD stats from nflverse (network I/O).

    Off-season / early-season often 404s for the current season parquet. Soft-
    return ``[]`` so the celery pipeline can continue (projector still runs).
    Does **not** fall back to a prior season — grading wrong weeks would be worse
    than skipping.
    """
    from app.services.etl.nfl.anytime_td_features import (
        _is_missing_nflverse_data_error,
        load_weekly_records_for_season,
    )

    try:
        records = load_weekly_records_for_season(int(season))
    except Exception as exc:
        if _is_missing_nflverse_data_error(exc):
            logger.warning(
                "nflverse weekly TD stats unavailable for season=%s week=%s (%s); "
                "skipping actuals",
                season,
                week,
                exc,
            )
            return []
        raise

    stats: list[dict[str, Any]] = []
    for row in records:
        try:
            row_season = int(row.get("season") or season)
            row_week = int(row.get("week") or 0)
        except (TypeError, ValueError):
            continue
        if row_season != season or row_week != week:
            continue
        position = str(row.get("position") or "").upper()
        if position not in SKILL_POSITIONS:
            continue
        opponent = (
            row.get("opponent_team") or row.get("opponent") or row.get("defteam") or ""
        )
        stats.append(
            {
                "player_id": row.get("player_id"),
                "player_name": row.get("player_display_name") or row.get("player_name"),
                "position": position,
                "team_name": row.get("recent_team") or row.get("team"),
                "opponent_team_name": opponent,
                "game_date": row.get("game_date") or row.get("gameday"),
                "passing_tds": row.get("passing_tds", 0),
                "rushing_tds": row.get("rushing_tds", 0),
                "receiving_tds": row.get("receiving_tds", 0),
            }
        )
    return stats


def run(
    *,
    season: int | None = None,
    week: int | None = None,
    player_stats: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade anytime-TD actuals for a week and upsert to DB."""
    resolved_season = resolve_nfl_season(season)
    resolved_week = week if week is not None else get_current_nfl_week(resolved_season)

    raw_stats = (
        player_stats
        if player_stats is not None
        else fetch_player_td_stats_nflverse(resolved_season, resolved_week)
    )

    normalized = [
        s for row in raw_stats if (s := _normalize_player_stat(row)) is not None
    ]

    if not normalized:
        return {
            "status": "ok",
            "season": resolved_season,
            "week": resolved_week,
            "actuals": 0,
        }

    db = SessionLocal()
    try:
        predictions = (
            db.query(NFLAnytimeTDPredictions)
            .filter_by(season=resolved_season, week=resolved_week)
            .all()
        )
        pred_by_player = {p.player_id: p for p in predictions}

        now = datetime.utcnow()
        upsert_rows = [
            build_actual_upsert_row(
                stat,
                season=resolved_season,
                week=resolved_week,
                prediction=pred_by_player.get(stat["player_id"]),
                now=now,
            )
            for stat in normalized
        ]

        upsert_many(
            db,
            NFLAnytimeTDActuals,
            upsert_rows,
            conflict_keys=["season", "week", "player_id"],
            update_keys=ACTUALS_UPSERT_UPDATE_KEYS,
        )
        db.commit()

        graded = sum(1 for row in upsert_rows if row["correct_prediction"] is not None)
        return {
            "status": "ok",
            "season": resolved_season,
            "week": resolved_week,
            "actuals": len(upsert_rows),
            "matched_predictions": sum(
                1 for stat in normalized if stat["player_id"] in pred_by_player
            ),
            "graded": graded,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
