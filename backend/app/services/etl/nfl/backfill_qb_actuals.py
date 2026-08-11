"""Backfill QB actuals from nflverse weekly (does not require stored predictions).

When a matching ``QBPredictions`` row exists, attaches predicted yards / ou_line
grading. Otherwise fills ``predicted_passing_yards`` from the tier table so
prod retrain has multi-season rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import nfl_data_py as nfl
import pandas as pd

from app.models.predictions_models import QBActuals, QBPredictions
from app.services.etl.nfl._db import db_session
from app.services.etl.nfl.qb_tiers import predict_qb_passing_yards


def _normalize_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().replace(".", " ").split())


def _weekly_qb_rows_from_pbp(season: int, week: int) -> list[dict[str, Any]]:
    """Fallback when nflverse weekly parquet is missing (e.g. mid-season 404)."""
    try:
        pbp = nfl.import_pbp_data([season])
    except Exception:
        return []
    if "season_type" in pbp.columns:
        pbp = pbp[pbp["season_type"] == "REG"]
    week_data = pbp[
        (pbp["week"] == week)
        & (pbp["play_type"] == "pass")
        & (pbp["passer_player_name"].notna())
    ]
    if week_data.empty:
        return []
    schedules = nfl.import_schedules([season])
    week_sched = schedules[schedules["week"] == week]
    if "game_type" in week_sched.columns:
        week_sched = week_sched[week_sched["game_type"] == "REG"]

    qb_stats = (
        week_data.groupby(["passer_player_id", "passer_player_name", "posteam"])
        .agg(
            {
                "passing_yards": "sum",
                "complete_pass": "sum",
                "pass_attempt": "sum",
                "pass_touchdown": "sum",
                "interception": "sum",
                "epa": "mean",
            }
        )
        .reset_index()
    )
    out: list[dict[str, Any]] = []
    for _, qb_row in qb_stats.iterrows():
        if float(qb_row["pass_attempt"] or 0) < 5:
            continue
        team = str(qb_row["posteam"])
        games = week_sched[
            (week_sched["home_team"] == team) | (week_sched["away_team"] == team)
        ]
        if games.empty:
            continue
        game = games.iloc[0]
        opponent = game["away_team"] if game["home_team"] == team else game["home_team"]
        gameday = game.get("gameday")
        try:
            game_date = pd.to_datetime(gameday).date() if gameday is not None else None
        except Exception:
            game_date = None
        if game_date is None:
            continue
        attempts = float(qb_row["pass_attempt"] or 0)
        completions = float(qb_row["complete_pass"] or 0)
        yards = float(qb_row["passing_yards"] or 0)
        out.append(
            {
                "qb_player_id": str(qb_row["passer_player_id"]),
                "qb_player_name": str(qb_row["passer_player_name"]),
                "team_name": team,
                "opponent_team_name": str(opponent),
                "venue_name": str(game.get("stadium") or "Unknown"),
                "game_date": game_date,
                "season": season,
                "week": week,
                "actual_passing_yards": yards,
                "actual_attempts": int(attempts),
                "actual_completions": int(completions),
                "actual_touchdowns": int(qb_row["pass_touchdown"] or 0),
                "actual_interceptions": int(qb_row["interception"] or 0),
                "actual_completion_pct": (
                    (completions / attempts) * 100.0 if attempts else 0.0
                ),
                "actual_yards_per_attempt": (yards / attempts if attempts else 0.0),
                "actual_passer_rating": 0.0,
                "epa_per_play": (
                    float(qb_row["epa"]) if pd.notna(qb_row["epa"]) else None
                ),
                "cpoe": None,
                "air_yards_per_attempt": None,
            }
        )
    return out


def _weekly_qb_rows(
    season: int,
    week: int,
    *,
    weekly: pd.DataFrame | None = None,
    schedules: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    if weekly is None:
        try:
            weekly = nfl.import_weekly_data([season])
        except Exception:
            weekly = None
    if weekly is None or getattr(weekly, "empty", True):
        return _weekly_qb_rows_from_pbp(season, week)
    frame = weekly
    if "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    if "position" in frame.columns:
        frame = frame[frame["position"] == "QB"]
    frame = frame[frame["week"] == week]
    if "attempts" in frame.columns:
        frame = frame[frame["attempts"].fillna(0) >= 5]

    if schedules is None:
        schedules = nfl.import_schedules([season])
    week_sched = schedules[schedules["week"] == week]
    if "game_type" in week_sched.columns:
        week_sched = week_sched[week_sched["game_type"] == "REG"]

    out: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        team = str(row.get("recent_team") or row.get("team") or "")
        games = week_sched[
            (week_sched["home_team"] == team) | (week_sched["away_team"] == team)
        ]
        if games.empty:
            continue
        game = games.iloc[0]
        opponent = game["away_team"] if game["home_team"] == team else game["home_team"]
        gameday = game.get("gameday")
        try:
            game_date = pd.to_datetime(gameday).date() if gameday is not None else None
        except Exception:
            game_date = None
        if game_date is None:
            continue
        attempts = float(row.get("attempts") or 0)
        completions = float(row.get("completions") or 0)
        yards = float(row.get("passing_yards") or 0)
        out.append(
            {
                "qb_player_id": str(row.get("player_id") or ""),
                "qb_player_name": str(
                    row.get("player_display_name") or row.get("player_name") or ""
                ),
                "team_name": team,
                "opponent_team_name": str(opponent),
                "venue_name": str(game.get("stadium") or "Unknown"),
                "game_date": game_date,
                "season": season,
                "week": week,
                "actual_passing_yards": yards,
                "actual_attempts": int(attempts),
                "actual_completions": int(completions),
                "actual_touchdowns": int(row.get("passing_tds") or 0),
                "actual_interceptions": int(row.get("interceptions") or 0),
                "actual_completion_pct": (
                    (completions / attempts) * 100.0 if attempts else 0.0
                ),
                "actual_yards_per_attempt": (yards / attempts if attempts else 0.0),
                "actual_passer_rating": float(row.get("passing_epa") or 0.0),
                "epa_per_play": (
                    float(row["passing_epa"])
                    if row.get("passing_epa") is not None
                    and pd.notna(row.get("passing_epa"))
                    else None
                ),
                "cpoe": None,
                "air_yards_per_attempt": None,
            }
        )
    return out


def _find_prediction(
    session, *, name: str, player_id: str, season: int, week: int
) -> QBPredictions | None:
    if player_id:
        pred = (
            session.query(QBPredictions)
            .filter_by(qb_player_id=player_id, season=season, week=week)
            .first()
        )
        if pred:
            return pred
    # Name match (exact then normalized)
    pred = (
        session.query(QBPredictions)
        .filter_by(qb_player_name=name, season=season, week=week)
        .first()
    )
    if pred:
        return pred
    name_n = _normalize_name(name)
    for cand in session.query(QBPredictions).filter_by(season=season, week=week).all():
        if _normalize_name(cand.qb_player_name or "") == name_n:
            return cand
    return None


def upsert_qb_actuals_for_week(
    season: int,
    week: int,
    *,
    min_attempts: int = 5,
    weekly: pd.DataFrame | None = None,
    schedules: pd.DataFrame | None = None,
) -> dict[str, int]:
    """Insert missing QB actuals for one week. Returns counts."""
    _ = min_attempts
    rows = _weekly_qb_rows(season, week, weekly=weekly, schedules=schedules)
    inserted = 0
    skipped = 0
    matched_pred = 0
    for actual in rows:
        existing = (
            db_session.query(QBActuals)
            .filter_by(
                qb_player_id=actual["qb_player_id"],
                season=season,
                week=week,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        pred = _find_prediction(
            db_session,
            name=actual["qb_player_name"],
            player_id=actual["qb_player_id"],
            season=season,
            week=week,
        )
        tier = predict_qb_passing_yards(
            actual["qb_player_name"], season, week, is_backup=False
        )
        predicted = float(tier["predicted_passing_yards"])
        method = "tier_backfill"
        confidence = float(tier.get("confidence") or 0.65)
        hit_ou = None
        correct = None
        if pred is not None:
            matched_pred += 1
            predicted = float(pred.predicted_passing_yards)
            method = pred.prediction_method or "matched_prediction"
            confidence = float(pred.model_confidence or confidence)
            if pred.ou_line is not None:
                line = float(pred.ou_line)
                actual_y = float(actual["actual_passing_yards"])
                if pred.betting_recommendation == "OVER":
                    hit_ou = actual_y > line
                    correct = hit_ou
                elif pred.betting_recommendation == "UNDER":
                    hit_ou = actual_y < line
                    correct = hit_ou

        actual_y = float(actual["actual_passing_yards"])
        err = actual_y - predicted
        acc = abs(err) / actual_y if actual_y > 0 else 0.0

        db_session.add(
            QBActuals(
                game_date=actual["game_date"],
                qb_player_id=actual["qb_player_id"],
                qb_player_name=actual["qb_player_name"],
                team_name=actual["team_name"],
                opponent_team_name=actual["opponent_team_name"],
                venue_name=actual["venue_name"],
                season=season,
                week=week,
                actual_passing_yards=actual_y,
                actual_attempts=actual["actual_attempts"],
                actual_completions=actual["actual_completions"],
                actual_touchdowns=actual["actual_touchdowns"],
                actual_interceptions=actual["actual_interceptions"],
                actual_completion_pct=actual["actual_completion_pct"],
                actual_yards_per_attempt=actual["actual_yards_per_attempt"],
                actual_passer_rating=actual["actual_passer_rating"],
                predicted_passing_yards=predicted,
                prediction_error=err,
                prediction_accuracy=acc,
                correct_prediction=bool(correct) if correct is not None else False,
                hit_over_under=hit_ou,
                prediction_confidence=confidence,
                prediction_method=method,
                epa_per_play=actual.get("epa_per_play"),
                cpoe=actual.get("cpoe"),
                air_yards_per_attempt=actual.get("air_yards_per_attempt"),
                data_collection_date=datetime.utcnow(),
            )
        )
        inserted += 1

    db_session.commit()
    print(
        f"QB {season} W{week}: inserted={inserted} skipped={skipped} "
        f"matched_pred={matched_pred} source_rows={len(rows)}"
    )
    return {
        "inserted": inserted,
        "skipped": skipped,
        "matched_pred": matched_pred,
        "source_rows": len(rows),
    }


def backfill_qb_actuals(
    *,
    seasons: list[int],
    start_week: int = 1,
    end_week: int = 18,
) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "inserted": 0,
        "skipped": 0,
        "matched_pred": 0,
        "seasons": seasons,
    }
    for season in seasons:
        print(f"Loading weekly + schedules for {season}...")
        weekly = None
        schedules = None
        try:
            weekly = nfl.import_weekly_data([season])
        except Exception as exc:
            print(f"weekly unavailable for {season}: {exc}; will use PBP fallback")
            weekly = None
        try:
            schedules = nfl.import_schedules([season])
        except Exception as exc:
            totals.setdefault("errors", []).append({season: str(exc)})
            continue
        for week in range(start_week, end_week + 1):
            stats = upsert_qb_actuals_for_week(
                season, week, weekly=weekly, schedules=schedules
            )
            totals["inserted"] += stats["inserted"]
            totals["skipped"] += stats["skipped"]
            totals["matched_pred"] += stats["matched_pred"]
    return totals
