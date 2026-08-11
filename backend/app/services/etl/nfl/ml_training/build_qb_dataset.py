"""Build QB passing yards training set from pred_qb_actuals + tier replay.

Uses leak-safe rolling form from prior actuals and weather context when present.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.services.etl.nfl.qb_tiers import predict_qb_passing_yards
from app.services.etl.nfl.qb_features import enrich_context_from_actual_row
from app.services.etl.nfl.qb_passing_yards_ml import (
    build_features_from_tier_prediction,
    feature_names,
)


def build(
    season_start: date,
    season_end: date,
    *,
    session=None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Rows from ``pred_qb_actuals`` with tier + form/matchup features.

    Requires DATABASE_URL when ``session`` is None.
    """
    from app.models.predictions_models import QBActuals

    if session is None:
        from app.core.database import SessionLocal

        session = SessionLocal()
        own = True
    else:
        own = False

    try:
        rows = (
            session.query(QBActuals)
            .filter(
                QBActuals.game_date >= season_start,
                QBActuals.game_date <= season_end,
            )
            .order_by(QBActuals.season, QBActuals.week)
            .all()
        )
        if not rows:
            return pd.DataFrame(columns=feature_names()), pd.Series(dtype=float)

        history: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "qb_player_id": r.qb_player_id,
                "qb_player_name": r.qb_player_name,
                "season": int(r.season),
                "week": int(r.week),
                "actual_passing_yards": float(r.actual_passing_yards),
            }
            if getattr(r, "actual_attempts", None) is not None:
                entry["actual_attempts"] = float(r.actual_attempts)
            if getattr(r, "actual_completions", None) is not None:
                entry["actual_completions"] = float(r.actual_completions)
            history.append(entry)

        from app.services.etl.nfl.ml_training.build_qb_dataset_nflverse import (
            _schedule_market_index,
        )

        seasons = sorted({int(r.season) for r in rows})
        market = _schedule_market_index(seasons)

        records: list[dict[str, float]] = []
        targets: list[float] = []
        for row in rows:
            tier_pred = predict_qb_passing_yards(
                row.qb_player_name,
                int(row.season),
                int(row.week),
                is_backup=False,
            )
            tier_yards = float(tier_pred["predicted_passing_yards"])
            player_key = row.qb_player_id or row.qb_player_name
            context = enrich_context_from_actual_row(
                row,
                history=history,
                player_key=str(player_key),
                tier_yards=tier_yards,
            )
            # Prefer joining stored prediction context when available
            pred_ctx = _prediction_context_for_actual(session, row)
            if pred_ctx:
                context.update({k: v for k, v in pred_ctx.items() if v is not None})
            # Real game lines from nflverse schedules when prediction context missing
            team = str(getattr(row, "team_name", "") or "").upper()
            mkt = market.get((int(row.season), int(row.week), team), {})
            for key, value in mkt.items():
                if context.get(key) is None and value is not None:
                    context[key] = value

            dynamic_tier = float(context.get("dynamic_tier_yards") or tier_yards)
            tier_pred_dyn = dict(tier_pred)
            tier_pred_dyn["predicted_passing_yards"] = dynamic_tier
            feats = build_features_from_tier_prediction(
                tier_pred_dyn,
                season=int(row.season),
                week=int(row.week),
                context=context,
            )
            records.append(feats)
            targets.append(float(row.actual_passing_yards))

        return pd.DataFrame(records), pd.Series(targets, name="actual_passing_yards")
    finally:
        if own:
            session.close()


def _prediction_context_for_actual(session, row) -> dict[str, Any]:
    """Pull implied total / home / weather / prop line from matching QBPredictions."""
    ctx: dict[str, Any] = {}
    pred = None
    try:
        from app.models.predictions_models import QBPredictions

        pred = (
            session.query(QBPredictions)
            .filter(
                QBPredictions.qb_player_id == row.qb_player_id,
                QBPredictions.season == row.season,
                QBPredictions.week == row.week,
            )
            .first()
        )
        if pred is None:
            pred = (
                session.query(QBPredictions)
                .filter(
                    QBPredictions.qb_player_name == row.qb_player_name,
                    QBPredictions.season == row.season,
                    QBPredictions.week == row.week,
                )
                .first()
            )
    except Exception:
        pred = None

    if pred is not None:
        if pred.implied_team_total is not None:
            ctx["implied_team_total"] = float(pred.implied_team_total)
        if pred.weather_temperature is not None:
            ctx["temperature"] = float(pred.weather_temperature)
        if pred.weather_wind_speed is not None:
            ctx["wind_speed"] = float(pred.weather_wind_speed)
        if pred.dome_game is not None:
            ctx["dome"] = bool(pred.dome_game)
        if getattr(pred, "spread", None) is not None:
            ctx["spread_line"] = float(pred.spread)
        if getattr(pred, "total_points", None) is not None:
            ctx["total_line"] = float(pred.total_points)
        if pred.ou_line is not None:
            ctx["pass_yds_line"] = float(pred.ou_line)
        fi = (
            pred.feature_importance if isinstance(pred.feature_importance, dict) else {}
        )
        nested = fi.get("features") if isinstance(fi.get("features"), dict) else {}
        for key in (
            "opp_pass_yds_allowed",
            "is_home",
            "rest_days",
            "rolling_yards_l3",
            "rolling_yards_l5",
            "season_avg_yards",
            "rolling_attempts_l3",
            "rolling_ypa_l3",
            "rolling_comp_pct_l3",
            "opp_cover_base",
            "opp_man_zone",
            "opp_scheme_pressure",
            "total_line",
            "spread_line",
            "pass_yds_line",
            "line_minus_tier",
            "dynamic_tier_yards",
        ):
            if nested.get(key) is not None:
                ctx[key] = nested[key]
            elif fi.get(key) is not None:
                ctx[key] = fi[key]

    if ctx.get("pass_yds_line") is None:
        try:
            from app.services.etl.nfl.historical_pass_yds_odds import (
                lookup_pass_yds_line,
            )

            hist = lookup_pass_yds_line(
                season=int(row.season),
                week=int(row.week),
                player_name=str(row.qb_player_name or ""),
                team_abbr=str(getattr(row, "team_name", "") or ""),
            )
            if hist is not None:
                ctx["pass_yds_line"] = float(hist)
        except Exception:
            pass
    return ctx
