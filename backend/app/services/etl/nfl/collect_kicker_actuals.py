"""NFL kicker actuals — nflverse FG totals matched to stored predictions.

Writes rows even when no prediction match exists (projected = league prior)
so ``pred_kicker_actuals`` stays populated for blend tuning / backtests.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import nfl_data_py as nfl
import pandas as pd
from sqlalchemy import and_

from app.models.predictions_models import Kickers, KickerActuals, KickerPredictions
from app.services.etl.nfl._db import db_session
from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season

_LEAGUE_PRIOR_FG = 1.85


def get_weekly_field_goal_data(
    week: int,
    season: int,
    *,
    pbp_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Field-goal attempt aggregates for one REG week from nflverse PBP."""
    print(f"Fetching NFL field goal data for week {week} of {season}...")
    try:
        if pbp_data is None:
            pbp_data = nfl.import_pbp_data([season])
    except Exception as exc:
        print(f"Error fetching field goal data: {exc}")
        return pd.DataFrame()

    frame = pbp_data
    if "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    frame = frame[frame["week"] == week]
    fg_data = frame[frame["field_goal_attempt"] == 1].copy()
    if fg_data.empty:
        print(f"No field goal data found for week {week}")
        return pd.DataFrame()

    print(f"Found {len(fg_data)} field goal attempts")
    weekly_stats = (
        fg_data.groupby(
            [
                "kicker_player_id",
                "kicker_player_name",
                "posteam",
                "defteam",
                "game_date",
            ]
        )
        .agg(
            {
                "field_goal_attempt": "sum",
                "field_goal_result": lambda x: (x == "made").sum(),
                "kick_distance": ["max", "mean"],
                "temp": "first",
                "wind": "first",
            }
        )
        .reset_index()
    )
    weekly_stats.columns = [
        "kicker_id",
        "kicker_name",
        "team",
        "opponent",
        "game_date",
        "attempts",
        "made",
        "longest_fg",
        "avg_distance",
        "temperature",
        "wind_speed",
    ]
    return weekly_stats


def _match_kicker_name(pred: Any, kicker_name_lower: str) -> bool:
    pred_name_attr = (
        "kicker_player_name" if hasattr(pred, "kicker_player_name") else "name"
    )
    pred_name = getattr(pred, pred_name_attr, "") or ""
    pred_name = pred_name.lower()

    if pred_name == kicker_name_lower:
        return True

    if "." in kicker_name_lower:
        actual_parts = kicker_name_lower.replace(".", " ").split()
        if len(actual_parts) >= 2:
            actual_initial = actual_parts[0][0]
            actual_last = actual_parts[-1]
            pred_parts = pred_name.split()
            if (
                len(pred_parts) >= 2
                and pred_parts[0][0] == actual_initial
                and pred_parts[-1] == actual_last
            ):
                return True

    if "." in pred_name:
        pred_parts = pred_name.replace(".", " ").split()
        if len(pred_parts) >= 2:
            pred_initial = pred_parts[0][0]
            pred_last = pred_parts[-1]
            actual_parts = kicker_name_lower.split()
            if (
                len(actual_parts) >= 2
                and actual_parts[0][0] == pred_initial
                and actual_parts[-1] == pred_last
            ):
                return True

    pred_parts = pred_name.split()
    actual_parts = kicker_name_lower.split()
    if (
        len(pred_parts) >= 2
        and len(actual_parts) >= 2
        and pred_parts[0][0] == actual_parts[0][0]
        and pred_parts[-1] == actual_parts[-1]
    ):
        return True

    pred_last = pred_parts[-1] if pred_parts else ""
    actual_last = actual_parts[-1] if actual_parts else ""
    return bool(pred_last and actual_last and pred_last == actual_last)


def _pred_game_date(pred: Any) -> date | None:
    gd = getattr(pred, "game_date", None)
    if gd is None:
        return None
    if isinstance(gd, datetime):
        return gd.date()
    if isinstance(gd, date):
        return gd
    try:
        return pd.to_datetime(gd).date()
    except Exception:
        return None


def _find_prediction(
    *,
    kicker_name: str,
    kicker_id: str,
    game_date: date,
    historical: list[Any],
    current: list[Any],
) -> tuple[Any | None, str | None, float]:
    """Return (prediction, source, projected_fgs)."""
    name_l = kicker_name.lower()
    # Prefer player-id match on historical rows
    for pred in historical:
        pid = str(getattr(pred, "kicker_player_id", "") or "")
        if pid and pid == str(kicker_id):
            pred_date = _pred_game_date(pred)
            if pred_date is None or abs((pred_date - game_date).days) <= 10:
                return pred, "historical", float(pred.predicted_fg_made)

    for pred in historical:
        if not _match_kicker_name(pred, name_l):
            continue
        pred_date = _pred_game_date(pred)
        if pred_date is None:
            continue
        if abs((pred_date - game_date).days) <= 10:
            return pred, "historical", float(pred.predicted_fg_made)

    for pred in current:
        if _match_kicker_name(pred, name_l):
            projected = float(
                getattr(pred, "projected_field_goals", None)
                or getattr(pred, "predicted_fg_made", _LEAGUE_PRIOR_FG)
            )
            return pred, "current", projected

    return None, None, _LEAGUE_PRIOR_FG


def match_predictions_with_actuals(
    week: int,
    season: int,
    *,
    require_prediction: bool = False,
    pbp_data: pd.DataFrame | None = None,
) -> dict[str, int]:
    """Grade one week into ``pred_kicker_actuals``. Returns counts."""
    actuals_df = get_weekly_field_goal_data(week, season, pbp_data=pbp_data)
    if actuals_df.empty:
        return {"processed": 0, "skipped_existing": 0, "no_prediction": 0}

    # Broad window: season kickoff through early February of next year
    week_start = date(season, 9, 1) + timedelta(weeks=max(0, week - 2))
    week_end = week_start + timedelta(days=21)
    historical_predictions = (
        db_session.query(KickerPredictions)
        .filter(
            and_(
                KickerPredictions.game_date
                >= datetime.combine(week_start, datetime.min.time()),
                KickerPredictions.game_date
                <= datetime.combine(week_end, datetime.max.time()),
            )
        )
        .all()
    )
    # Fallback: all preds whose game_date falls on actual game dates this week
    if len(historical_predictions) < 5:
        historical_predictions = db_session.query(KickerPredictions).all()
    current_predictions = db_session.query(Kickers).all()
    print(
        f"📅 week {week}: {len(historical_predictions)} hist preds, "
        f"{len(current_predictions)} current"
    )

    processed = 0
    skipped_existing = 0
    no_prediction = 0

    for _, actual in actuals_df.iterrows():
        kicker_name = str(actual["kicker_name"])
        game_date = pd.to_datetime(actual["game_date"]).date()
        kicker_id = str(actual["kicker_id"])

        existing = (
            db_session.query(KickerActuals)
            .filter(
                and_(
                    KickerActuals.kicker_id == kicker_id,
                    KickerActuals.date == game_date,
                )
            )
            .first()
        )
        if existing:
            skipped_existing += 1
            continue

        prediction, source, projected_fgs = _find_prediction(
            kicker_name=kicker_name,
            kicker_id=kicker_id,
            game_date=game_date,
            historical=historical_predictions,
            current=current_predictions,
        )
        if prediction is None:
            no_prediction += 1
            if require_prediction:
                print(f"❌ No prediction for {kicker_name} on {game_date}")
                continue
            source = "prior"
            projected_fgs = _LEAGUE_PRIOR_FG

        actual_made = int(actual["made"])
        hit_over_1_5 = actual_made >= 2
        if projected_fgs >= 1.75:
            correct_prediction = hit_over_1_5
        elif projected_fgs <= 1.25:
            correct_prediction = not hit_over_1_5
        else:
            correct_prediction = None
        confidence = abs(projected_fgs - 1.5) / 1.5

        db_session.add(
            KickerActuals(
                date=game_date,
                kicker_id=kicker_id,
                kicker_name=kicker_name,
                team_name=actual["team"],
                opponent_name=actual["opponent"],
                venue_name=f"{actual['team']} vs {actual['opponent']}",
                actual_field_goals_made=actual_made,
                actual_field_goals_attempted=int(actual["attempts"]),
                actual_longest_fg=(
                    int(actual["longest_fg"])
                    if pd.notna(actual["longest_fg"])
                    else None
                ),
                game_temperature=(
                    float(actual["temperature"])
                    if pd.notna(actual["temperature"])
                    else None
                ),
                game_wind_speed=(
                    float(actual["wind_speed"])
                    if pd.notna(actual["wind_speed"])
                    else None
                ),
                projected_field_goals=float(projected_fgs),
                hit_over_1_5=hit_over_1_5,
                correct_prediction=correct_prediction,
                prediction_confidence=confidence,
            )
        )
        processed += 1
        print(
            f"✅ {kicker_name}: {actual_made}/{int(actual['attempts'])} "
            f"proj={projected_fgs:.2f} [{source}]"
        )

    db_session.commit()
    print(
        f"📊 week {week}: wrote {processed}, existing {skipped_existing}, no_pred {no_prediction}"
    )
    return {
        "processed": processed,
        "skipped_existing": skipped_existing,
        "no_prediction": no_prediction,
    }


def update_kicker_actuals(
    week: int | None = None,
    season: int | None = None,
    *,
    require_prediction: bool = False,
    pbp_data: pd.DataFrame | None = None,
) -> dict[str, int]:
    """Update kicker actuals for one week (defaults: env season / current week)."""
    resolved_season = resolve_nfl_season(season)
    resolved_week = week if week is not None else get_current_nfl_week(resolved_season)
    print(
        f"🏈 Updating kicker actuals for NFL Week {resolved_week} "
        f"(season {resolved_season})"
    )
    return match_predictions_with_actuals(
        resolved_week,
        resolved_season,
        require_prediction=require_prediction,
        pbp_data=pbp_data,
    )


def backfill_kicker_actuals(
    *,
    season: int,
    start_week: int = 1,
    end_week: int = 18,
    require_prediction: bool = False,
) -> dict[str, Any]:
    """Backfill REG weeks into ``pred_kicker_actuals``."""
    print(f"Loading PBP once for season {season}...")
    try:
        pbp_data = nfl.import_pbp_data([season])
    except Exception as exc:
        return {"processed": 0, "error": str(exc), "season": season}

    totals = {"processed": 0, "skipped_existing": 0, "no_prediction": 0, "weeks": []}
    for week in range(start_week, end_week + 1):
        stats = update_kicker_actuals(
            week,
            season,
            require_prediction=require_prediction,
            pbp_data=pbp_data,
        )
        totals["processed"] += stats["processed"]
        totals["skipped_existing"] += stats["skipped_existing"]
        totals["no_prediction"] += stats["no_prediction"]
        totals["weeks"].append({"week": week, **stats})
    totals["season"] = season
    return totals


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        # Prefer prior completed season when default calendar is pre-kickoff week 1
        season = resolve_nfl_season(None)
        week = get_current_nfl_week(season)
        # In Aug before kickoff, grade the previous season's final week instead
        today = date.today()
        if today.month < 9 and week <= 1:
            season = season - 1
            week = 18
        stats = update_kicker_actuals(week, season)
        return {
            "status": "ok",
            "task": "nfl_collect_kicker_actuals",
            "season": season,
            "week": week,
            **stats,
        }
    finally:
        close_session()


if __name__ == "__main__":
    import argparse

    from app.services.etl.nfl._db import close_session, init_session

    parser = argparse.ArgumentParser(description="Collect NFL kicker actual results")
    parser.add_argument("--week", type=int, help="NFL week number (1-18)")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Backfill start_week..end_week for --season",
    )
    parser.add_argument("--start-week", type=int, default=1)
    parser.add_argument("--end-week", type=int, default=18)
    parser.add_argument(
        "--require-prediction",
        action="store_true",
        help="Skip rows without a matching prediction",
    )
    args = parser.parse_args()

    init_session()
    try:
        if args.backfill:
            if args.season is None:
                raise SystemExit("--season required with --backfill")
            out = backfill_kicker_actuals(
                season=args.season,
                start_week=args.start_week,
                end_week=args.end_week,
                require_prediction=args.require_prediction,
            )
            print(out)
        else:
            update_kicker_actuals(
                args.week,
                args.season,
                require_prediction=args.require_prediction,
            )
    finally:
        close_session()
