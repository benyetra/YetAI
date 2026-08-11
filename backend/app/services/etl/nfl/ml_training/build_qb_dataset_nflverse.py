"""Build QB yards training features from nflverse weekly (no DB required)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.etl.nfl.qb_features import (
    estimate_opp_air_yards_allowed_from_weekly,
    estimate_opp_defense_from_weekly,
    estimate_opp_pass_allowed_from_weekly,
    form_features_from_prior_yards,
    form_volume_features_from_prior,
    implied_team_total_from_market,
    prior_game_stats_for_player,
    prior_yards_for_player,
    scheme_features_for_opponent,
)
from app.services.etl.nfl.qb_passing_yards_ml import (
    build_features_from_tier_prediction,
    feature_names,
)
from app.services.etl.nfl.qb_tiers import predict_qb_passing_yards


def _load_schemes() -> dict[str, dict[str, Any]]:
    try:
        from app.services.etl.nfl.scheme_loader import load_schemes_from_yaml

        return load_schemes_from_yaml()
    except Exception:
        return {}


def _schedule_market_index(seasons: list[int]) -> dict[tuple[int, int, str], dict]:
    """Map (season, week, team_abbr) → total_line / spread_for_team / is_home."""
    out: dict[tuple[int, int, str], dict] = {}
    try:
        import nfl_data_py as nfl
    except ImportError:
        # Optional for prod DB-backed eval; callers tolerate empty market index.
        return out
    try:
        schedules = nfl.import_schedules([int(s) for s in seasons])
    except Exception:
        return out
    if schedules is None or getattr(schedules, "empty", True):
        return out
    if "game_type" in schedules.columns:
        schedules = schedules[schedules["game_type"] == "REG"]
    for _, row in schedules.iterrows():
        try:
            season = int(row.get("season") or 0)
            week = int(row.get("week") or 0)
        except (TypeError, ValueError):
            continue
        home = str(row.get("home_team") or "").upper()
        away = str(row.get("away_team") or "").upper()
        total = row.get("total_line")
        spread = row.get("spread_line")  # home perspective
        try:
            total_f = float(total) if total is not None and pd.notna(total) else None
        except (TypeError, ValueError):
            total_f = None
        try:
            spread_home = (
                float(spread) if spread is not None and pd.notna(spread) else None
            )
        except (TypeError, ValueError):
            spread_home = None
        roof = str(row.get("roof") or "").lower()
        dome = roof in {"dome", "closed", "retractable"}
        temp = row.get("temp")
        wind = row.get("wind")
        for team, is_home, team_spread in (
            (home, True, spread_home),
            (
                away,
                False,
                (-spread_home if spread_home is not None else None),
            ),
        ):
            if not team:
                continue
            implied = None
            if total_f is not None and team_spread is not None:
                implied = implied_team_total_from_market(
                    total_line=total_f, spread_line=team_spread
                )
            out[(season, week, team)] = {
                "total_line": total_f,
                "spread_line": team_spread,
                "implied_team_total": implied,
                "is_home": 1.0 if is_home else 0.0,
                "dome": dome,
                "temperature": (
                    float(temp) if temp is not None and pd.notna(temp) else None
                ),
                "wind_speed": (
                    float(wind) if wind is not None and pd.notna(wind) else None
                ),
            }
    return out


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
                "completions": (
                    float(row["completions"])
                    if row.get("completions") is not None
                    and pd.notna(row.get("completions"))
                    else None
                ),
                "sacks": (
                    float(row["sacks"])
                    if row.get("sacks") is not None and pd.notna(row.get("sacks"))
                    else None
                ),
                "passing_air_yards": (
                    float(row["passing_air_yards"])
                    if row.get("passing_air_yards") is not None
                    and pd.notna(row.get("passing_air_yards"))
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

    market = _schedule_market_index(seasons)
    schemes = _load_schemes()
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
        prior_stats = prior_game_stats_for_player(
            history_sorted,
            player_key=str(player_key),
            season=season,
            week=week,
        )
        volume = form_volume_features_from_prior(prior_stats)
        opp = str(row.get("opponent_team") or "")
        team = str(row.get("recent_team") or "").upper()
        opp_allowed = estimate_opp_pass_allowed_from_weekly(
            history_sorted, opponent_abbr=opp, season=season, week=week
        )
        opp_air = estimate_opp_air_yards_allowed_from_weekly(
            history_sorted, opponent_abbr=opp, season=season, week=week
        )
        defense = estimate_opp_defense_from_weekly(
            history_sorted, opponent_abbr=opp, season=season, week=week
        )
        scheme = scheme_features_for_opponent(opp, schemes=schemes)
        mkt = market.get((season, week, team), {})
        context: dict[str, Any] = {**form, **volume, **defense, **scheme}
        if opp_allowed is not None:
            context["opp_pass_yds_allowed"] = opp_allowed
        if opp_air is not None:
            context["opp_air_yards_allowed"] = opp_air
        for key in (
            "total_line",
            "spread_line",
            "implied_team_total",
            "is_home",
            "dome",
            "temperature",
            "wind_speed",
        ):
            if mkt.get(key) is not None:
                context[key] = mkt[key]
        # Prefer historical Odds index; else tier-anchor (line_is_real=False).
        pass_line = None
        try:
            from app.services.etl.nfl.historical_pass_yds_odds import (
                lookup_pass_yds_line,
            )

            pass_line = lookup_pass_yds_line(
                season=season,
                week=week,
                player_name=name,
                team_abbr=team or None,
            )
        except Exception:
            pass_line = None
        if pass_line is not None:
            context["pass_yds_line"] = float(pass_line)
            context["line_is_real"] = True
        else:
            context["pass_yds_line"] = tier_yards
            context["line_is_real"] = False
        context["opponent_abbr"] = opp
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
                "recent_team": team,
                "tier_yards": tier_yards,
                "actual_passing_yards": float(row["actual_passing_yards"]),
            }
        )
    return (
        pd.DataFrame(records),
        pd.Series(targets, name="actual_passing_yards"),
        pd.DataFrame(meta_rows),
    )
