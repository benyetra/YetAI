"""Build QB yards training features from nflverse weekly (no DB required)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.etl.nfl.qb_features import (
    estimate_opp_defense_from_weekly,
    estimate_opp_pass_allowed_from_weekly,
    form_features_from_prior_yards,
    prior_yards_for_player,
)
from app.services.etl.nfl.qb_passing_yards_ml import (
    build_features_from_tier_prediction,
    feature_names,
)
from app.services.etl.nfl.qb_tiers import predict_qb_passing_yards


def _weekly_records(seasons: list[int]) -> list[dict[str, Any]]:
    import nfl_data_py as nfl

    frames = []
    for season in seasons:
        try:
            weekly = nfl.import_weekly_data([int(season)])
        except Exception:
            continue
        if weekly is None or getattr(weekly, "empty", True):
            continue
        frames.append(weekly)
    if not frames:
        return []
    weekly = pd.concat(frames, ignore_index=True)
    if "season_type" in weekly.columns:
        weekly = weekly[weekly["season_type"] == "REG"]
    if "position" in weekly.columns:
        weekly = weekly[weekly["position"] == "QB"]
    # Starters / meaningful pass volume
    if "attempts" in weekly.columns:
        weekly = weekly[weekly["attempts"].fillna(0) >= 10]

    records: list[dict[str, Any]] = []
    for _, row in weekly.iterrows():
        records.append(
            {
                "qb_player_id": str(row.get("player_id") or ""),
                "qb_player_name": str(
                    row.get("player_display_name") or row.get("player_name") or ""
                ),
                "season": int(row.get("season") or 0),
                "week": int(row.get("week") or 0),
                "actual_passing_yards": float(row.get("passing_yards") or 0),
                "recent_team": str(row.get("recent_team") or row.get("team") or ""),
                "opponent_team": str(row.get("opponent_team") or ""),
                "position": "QB",
                "passing_yards": float(row.get("passing_yards") or 0),
                "passing_epa": (
                    float(row["passing_epa"])
                    if row.get("passing_epa") is not None
                    and pd.notna(row.get("passing_epa"))
                    else None
                ),
                "attempts": (
                    float(row["attempts"])
                    if row.get("attempts") is not None and pd.notna(row.get("attempts"))
                    else None
                ),
                "sacks": (
                    float(row["sacks"])
                    if row.get("sacks") is not None and pd.notna(row.get("sacks"))
                    else None
                ),
            }
        )
    return records


def build_from_nflverse(
    seasons: list[int],
    *,
    min_attempts: int = 10,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """
    Leak-safe feature matrix from nflverse weekly QB games.

    Returns ``(features, target_yards, meta)`` where meta has season/week/name/id.
    """
    _ = min_attempts
    history = _weekly_records(seasons)
    if not history:
        return (
            pd.DataFrame(columns=feature_names()),
            pd.Series(dtype=float),
            pd.DataFrame(),
        )

    history_sorted = sorted(history, key=lambda r: (r["season"], r["week"]))
    records: list[dict[str, float]] = []
    targets: list[float] = []
    meta_rows: list[dict[str, Any]] = []

    for row in history_sorted:
        name = row["qb_player_name"]
        season = int(row["season"])
        week = int(row["week"])
        tier_pred = predict_qb_passing_yards(name, season, week, is_backup=False)
        tier_yards = float(tier_pred["predicted_passing_yards"])
        player_key = row["qb_player_id"] or name
        prior = prior_yards_for_player(
            history_sorted,
            player_key=str(player_key),
            season=season,
            week=week,
        )
        form = form_features_from_prior_yards(prior, tier_yards=tier_yards)
        opp = str(row.get("opponent_team") or "")
        opp_allowed = estimate_opp_pass_allowed_from_weekly(
            history_sorted, opponent_abbr=opp, season=season, week=week
        )
        defense = estimate_opp_defense_from_weekly(
            history_sorted, opponent_abbr=opp, season=season, week=week
        )
        context: dict[str, Any] = {**form, **defense}
        if opp_allowed is not None:
            context["opp_pass_yds_allowed"] = opp_allowed
        feats = build_features_from_tier_prediction(
            tier_pred, season=season, week=week, context=context
        )
        records.append(feats)
        targets.append(float(row["actual_passing_yards"]))
        meta_rows.append(
            {
                "qb_player_id": row["qb_player_id"],
                "qb_player_name": name,
                "season": season,
                "week": week,
                "opponent_team": opp,
                "tier_yards": tier_yards,
                "actual_passing_yards": float(row["actual_passing_yards"]),
            }
        )

    return (
        pd.DataFrame(records),
        pd.Series(targets, name="actual_passing_yards"),
        pd.DataFrame(meta_rows),
    )
