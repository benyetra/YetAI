#!/usr/bin/env python3
"""
Dynamic QB Predictions Script for Heroku
Uses nfl-data-py to dynamically detect starting QBs and create predictions
"""

import warnings
from datetime import datetime, date, timedelta
from typing import Dict, List

import nfl_data_py as nfl
import pandas as pd

from app.models.predictions_models import QBPredictions
from app.services.etl.nfl._db import db_session
from app.services.etl.nfl.nfl_common import (
    _first_regular_season_thursday,
    get_current_nfl_week,
    get_nfl_season,
)
from app.services.etl.nfl.qb_passing_yards_ml import enrich_qb_prediction_for_write
from app.services.etl.nfl.qb_tiers import predict_qb_passing_yards

warnings.filterwarnings("ignore")


def get_team_id_mapping():
    """Map NFL team abbreviations to our database team IDs"""
    return {
        "ATL": 1,
        "BUF": 2,
        "CHI": 3,
        "CIN": 4,
        "CLE": 5,
        "DAL": 6,
        "DEN": 7,
        "DET": 8,
        "GB": 9,
        "TEN": 10,
        "IND": 11,
        "KC": 12,
        "LV": 13,
        "LAR": 14,
        "MIA": 15,
        "MIN": 16,
        "NE": 17,
        "NO": 18,
        "NYG": 19,
        "NYJ": 20,
        "PHI": 21,
        "ARI": 22,
        "PIT": 23,
        "LAC": 24,
        "SF": 25,
        "SEA": 26,
        "TB": 27,
        "WAS": 28,
        "CAR": 29,
        "JAX": 30,
        "LAS": 13,
        "BAL": 33,
        "HOU": 34,
        "LA": 14,  # Handle LA as LAR
    }


def get_team_full_name(abbreviation: str) -> str:
    """Convert team abbreviation to full name"""
    team_names = {
        "ATL": "Atlanta Falcons",
        "BUF": "Buffalo Bills",
        "CHI": "Chicago Bears",
        "CIN": "Cincinnati Bengals",
        "CLE": "Cleveland Browns",
        "DAL": "Dallas Cowboys",
        "DEN": "Denver Broncos",
        "DET": "Detroit Lions",
        "GB": "Green Bay Packers",
        "TEN": "Tennessee Titans",
        "IND": "Indianapolis Colts",
        "KC": "Kansas City Chiefs",
        "LV": "Las Vegas Raiders",
        "LAR": "Los Angeles Rams",
        "MIA": "Miami Dolphins",
        "MIN": "Minnesota Vikings",
        "NE": "New England Patriots",
        "NO": "New Orleans Saints",
        "NYG": "New York Giants",
        "NYJ": "New York Jets",
        "PHI": "Philadelphia Eagles",
        "ARI": "Arizona Cardinals",
        "PIT": "Pittsburgh Steelers",
        "LAC": "Los Angeles Chargers",
        "SF": "San Francisco 49ers",
        "SEA": "Seattle Seahawks",
        "TB": "Tampa Bay Buccaneers",
        "WAS": "Washington Commanders",
        "CAR": "Carolina Panthers",
        "JAX": "Jacksonville Jaguars",
        "BAL": "Baltimore Ravens",
        "HOU": "Houston Texans",
        "LA": "Los Angeles Rams",
    }
    return team_names.get(abbreviation, f"{abbreviation} Team")


def _week_reg_schedules(season: int, week: int) -> pd.DataFrame:
    schedules = nfl.import_schedules([season])
    week_schedule = schedules[schedules["week"] == week]
    if "game_type" in week_schedule.columns:
        week_schedule = week_schedule[week_schedule["game_type"] == "REG"]
    return week_schedule


def _team_game_row(team_abbr: str, season: int, week: int) -> pd.Series | None:
    week_schedule = _week_reg_schedules(season, week)
    team_game = week_schedule[
        (week_schedule["home_team"] == team_abbr)
        | (week_schedule["away_team"] == team_abbr)
    ]
    if team_game.empty:
        return None
    return team_game.iloc[0]


def get_game_kickoff(team_abbr: str, season: int, week: int) -> datetime | None:
    """Return scheduled kickoff for a team's REG game in the given week."""
    try:
        game = _team_game_row(team_abbr, season, week)
        if game is None:
            return None

        gameday = game.get("gameday")
        gametime = game.get("gametime")
        if pd.isna(gameday) or not gameday:
            return None

        gameday_str = str(gameday)
        if pd.isna(gametime) or not gametime:
            return datetime.strptime(gameday_str, "%Y-%m-%d")

        return datetime.strptime(f"{gameday_str} {gametime}", "%Y-%m-%d %H:%M")
    except Exception as e:
        print(f"⚠️ Error getting kickoff for {team_abbr}: {e}")
        return None


def _fallback_game_date(season: int, week: int) -> datetime:
    """Noon on the Thursday of the requested regular-season week."""
    thursday = _first_regular_season_thursday(season) + timedelta(days=(week - 1) * 7)
    return datetime(thursday.year, thursday.month, thursday.day, 12, 0, 0)


def _resolve_game_date(team_abbr: str, season: int, week: int) -> datetime:
    return get_game_kickoff(team_abbr, season, week) or _fallback_game_date(
        season, week
    )


def get_team_opponent(team_abbr: str, season: int, week: int) -> str:
    """Get opponent team abbreviation for a given team in a specific week"""
    try:
        game = _team_game_row(team_abbr, season, week)
        if game is not None:
            if game["home_team"] == team_abbr:
                return game["away_team"]
            return game["home_team"]

        return "TBD"  # No game found

    except Exception as e:
        print(f"⚠️ Error getting opponent for {team_abbr}: {e}")
        return "TBD"


def team_is_home(team_abbr: str, season: int, week: int) -> float:
    """1.0 home / 0.0 away / 0.5 unknown."""
    try:
        game = _team_game_row(team_abbr, season, week)
        if game is None:
            return 0.5
        if game["home_team"] == team_abbr:
            return 1.0
        if game["away_team"] == team_abbr:
            return 0.0
    except Exception:
        pass
    return 0.5


def _load_weekly_qb_history(season: int) -> list[dict]:
    """nflverse weekly QB rows for rolling form / opp allowed (best-effort)."""
    try:
        weekly = nfl.import_weekly_data([season])
    except Exception as e:
        print(f"⚠️ weekly data unavailable for QB features: {e}")
        return []
    if weekly is None or getattr(weekly, "empty", True):
        return []
    records: list[dict] = []
    for _, row in weekly.iterrows():
        pos = str(row.get("position") or "").upper()
        if pos and pos != "QB":
            continue
        records.append(
            {
                "qb_player_id": str(row.get("player_id") or ""),
                "qb_player_name": str(
                    row.get("player_display_name") or row.get("player_name") or ""
                ),
                "season": int(row.get("season") or season),
                "week": int(row.get("week") or 0),
                "actual_passing_yards": float(row.get("passing_yards") or 0),
                "recent_team": str(row.get("recent_team") or row.get("team") or ""),
                "opponent_team": str(row.get("opponent_team") or ""),
                "position": "QB",
                "passing_yards": float(row.get("passing_yards") or 0),
                "passing_epa": (
                    float(row["passing_epa"])
                    if row.get("passing_epa") is not None
                    and not pd.isna(row.get("passing_epa"))
                    else None
                ),
                "attempts": (
                    float(row["attempts"])
                    if row.get("attempts") is not None
                    and not pd.isna(row.get("attempts"))
                    else None
                ),
                "completions": (
                    float(row["completions"])
                    if row.get("completions") is not None
                    and not pd.isna(row.get("completions"))
                    else None
                ),
                "sacks": (
                    float(row["sacks"])
                    if row.get("sacks") is not None and not pd.isna(row.get("sacks"))
                    else None
                ),
                "passing_air_yards": (
                    float(row["passing_air_yards"])
                    if row.get("passing_air_yards") is not None
                    and not pd.isna(row.get("passing_air_yards"))
                    else None
                ),
            }
        )
    return records


def _implied_team_total_for_team(
    team_abbr: str, season: int, week: int
) -> float | None:
    """Best-effort implied team total from pred_nfl_game_lines."""
    try:
        from app.models.predictions_models import NFLGameLines
        from app.services.etl.nfl.anytime_td_features import game_env_from_line
        from app.services.etl.nfl.team_names import (
            _CANONICAL_BY_ABBR,
            normalize_team_name,
        )

        team_name = _CANONICAL_BY_ABBR.get(team_abbr.upper()) or get_team_full_name(
            team_abbr
        )
        kickoff = get_game_kickoff(team_abbr, season, week)
        lines = db_session.query(NFLGameLines).all()
        if not lines:
            return None
        target = normalize_team_name(team_name)
        kickoff_date = kickoff.date() if kickoff is not None else None
        for line in lines:
            home = normalize_team_name(getattr(line, "home_team_name", "") or "")
            away = normalize_team_name(getattr(line, "away_team_name", "") or "")
            if target not in {home, away}:
                continue
            if kickoff_date is not None and getattr(line, "game_date", None):
                if line.game_date != kickoff_date:
                    continue
            env = game_env_from_line(line, home=(target == home))
            if env.get("implied_team_total") is not None:
                return float(env["implied_team_total"])
    except Exception as e:
        print(f"⚠️ implied total lookup failed for {team_abbr}: {e}")
    return None


def _market_lines_for_team(team_abbr: str, season: int, week: int) -> dict:
    """total_line / team spread / weather from nflverse schedules."""
    try:
        game = _team_game_row(team_abbr, season, week)
        if game is None:
            return {}
        home = str(game.get("home_team") or "").upper()
        is_home = team_abbr.strip().upper() == home
        total = game.get("total_line")
        spread_home = game.get("spread_line")
        try:
            total_f = float(total) if total is not None and pd.notna(total) else None
        except (TypeError, ValueError):
            total_f = None
        try:
            spread_home_f = (
                float(spread_home)
                if spread_home is not None and pd.notna(spread_home)
                else None
            )
        except (TypeError, ValueError):
            spread_home_f = None
        team_spread = None
        if spread_home_f is not None:
            team_spread = spread_home_f if is_home else -spread_home_f
        roof = str(game.get("roof") or "").lower()
        out: dict = {
            "total_line": total_f,
            "spread_line": team_spread,
            "is_home": 1.0 if is_home else 0.0,
            "dome": roof in {"dome", "closed", "retractable"},
        }
        temp = game.get("temp")
        wind = game.get("wind")
        if temp is not None and pd.notna(temp):
            out["temperature"] = float(temp)
        if wind is not None and pd.notna(wind):
            out["wind_speed"] = float(wind)
        return out
    except Exception as e:
        print(f"⚠️ market lines lookup failed for {team_abbr}: {e}")
        return {}


def build_qb_prediction_context(
    *,
    qb_name: str,
    player_id: str,
    team_abbr: str,
    opponent_abbr: str,
    season: int,
    week: int,
    weekly_history: list[dict] | None = None,
    injury_status: str | None = None,
    is_backup: bool = False,
    hours_to_kickoff: float | None = None,
    pass_yds_line: float | None = None,
    static_tier_yards: float | None = None,
) -> dict:
    """Assemble matchup/form context for GBM features."""
    from app.services.etl.nfl.qb_features import (
        blend_tier_with_form,
        estimate_opp_air_yards_allowed_from_weekly,
        estimate_opp_defense_from_weekly,
        estimate_opp_pass_allowed_from_weekly,
        form_features_from_prior_yards,
        form_volume_features_from_prior,
        prior_game_stats_for_player,
        prior_yards_for_player,
        scheme_features_for_opponent,
    )
    from app.services.etl.nfl.qb_late_availability import late_injury_risk

    history = weekly_history if weekly_history is not None else []
    player_key = player_id or qb_name
    prior = prior_yards_for_player(
        history,
        player_key=player_key,
        season=season,
        week=week,
    )
    if not prior and qb_name:
        prior = prior_yards_for_player(
            history,
            player_key=qb_name,
            season=season,
            week=week,
        )
    prior_stats = prior_game_stats_for_player(
        history,
        player_key=player_key,
        season=season,
        week=week,
    )
    if not prior_stats and qb_name:
        prior_stats = prior_game_stats_for_player(
            history,
            player_key=qb_name,
            season=season,
            week=week,
        )
    tier_anchor = float(static_tier_yards) if static_tier_yards is not None else 210.0
    form = form_features_from_prior_yards(prior, tier_yards=tier_anchor)
    volume = form_volume_features_from_prior(prior_stats)
    dynamic_tier = blend_tier_with_form(tier_anchor, prior)
    opp_allowed = estimate_opp_pass_allowed_from_weekly(
        history,
        opponent_abbr=opponent_abbr or "",
        season=season,
        week=week,
    )
    opp_air = estimate_opp_air_yards_allowed_from_weekly(
        history,
        opponent_abbr=opponent_abbr or "",
        season=season,
        week=week,
    )
    defense = estimate_opp_defense_from_weekly(
        history,
        opponent_abbr=opponent_abbr or "",
        season=season,
        week=week,
    )
    scheme = scheme_features_for_opponent(opponent_abbr or "")
    implied = _implied_team_total_for_team(team_abbr, season, week)
    market = _market_lines_for_team(team_abbr, season, week)
    risk = late_injury_risk(
        injury_status,
        hours_to_kickoff=hours_to_kickoff,
        is_backup=is_backup,
    )
    ctx: dict = {
        **form,
        **volume,
        **defense,
        **scheme,
        "dynamic_tier_yards": dynamic_tier,
        "is_home": market.get("is_home", team_is_home(team_abbr, season, week)),
        "team_abbr": team_abbr,
        "opponent_abbr": opponent_abbr,
        "injury_status": injury_status or "Healthy",
        "injury_risk": risk,
    }
    if opp_allowed is not None:
        ctx["opp_pass_yds_allowed"] = opp_allowed
    if opp_air is not None:
        ctx["opp_air_yards_allowed"] = opp_air
    if implied is not None:
        ctx["implied_team_total"] = implied
    elif market.get("implied_team_total") is not None:
        ctx["implied_team_total"] = market["implied_team_total"]
    for key in ("total_line", "spread_line", "dome", "temperature", "wind_speed"):
        if market.get(key) is not None:
            ctx[key] = market[key]
    if pass_yds_line is not None:
        ctx["pass_yds_line"] = float(pass_yds_line)
    if week > 1 and history:
        played_prior = any(
            int(r.get("week") or 0) == week - 1
            and (
                str(r.get("qb_player_id") or "") == str(player_id)
                or str(r.get("qb_player_name") or "").lower() == qb_name.lower()
            )
            for r in history
        )
        ctx["rest_days"] = 7.0 if played_prior else 14.0
    return ctx


def get_dynamic_starting_qbs(season: int, week: int) -> List[Dict]:
    """Get current starting QBs using depth charts and injury data"""
    from app.services.etl.nfl.qb_late_availability import (
        hours_until_kickoff,
        should_promote_backup,
    )
    from app.services.etl.nfl.qb_starter_registry import (
        filter_depth_charts_to_latest_snapshot,
        get_starter_override,
        resolve_qb_starter_for_team,
    )

    print(f"🔍 Getting starting QBs for {season} Week {week}")

    # Get depth charts
    try:
        depth_charts = nfl.import_depth_charts([season])
        print(f"✅ Loaded {len(depth_charts)} depth chart entries")
    except Exception as e:
        print(f"❌ Error loading depth charts: {e}")
        return []

    # Get injury data
    try:
        injuries = nfl.import_injuries([season])
        print(f"✅ Loaded {len(injuries)} injury reports")
    except Exception as e:
        print(f"⚠️ Warning: Could not load injuries: {e}")
        injuries = pd.DataFrame()

    # Handle different data formats for 2024 vs 2025
    if "position" in depth_charts.columns:
        # 2024 format
        qb_depth = depth_charts[depth_charts["position"] == "QB"].copy()
        print(f"📊 Found {len(qb_depth)} QB depth chart entries (2024 format)")

        # Get the most recent week data for each team
        latest_week_per_team = qb_depth.groupby("club_code")["week"].max().reset_index()
        use_2025_format = False
    else:
        # 2025 format — many snapshots share one frame; keep latest only
        qb_depth_raw = depth_charts[depth_charts["pos_abb"] == "QB"].copy()
        print(
            f"📊 Found {len(qb_depth_raw)} QB depth chart entries (2025 format, all snapshots)"
        )
        qb_depth = filter_depth_charts_to_latest_snapshot(qb_depth_raw)
        if "dt" in qb_depth.columns and not qb_depth.empty:
            print(
                f"📊 Using latest snapshot ({qb_depth['dt'].iloc[0]}): "
                f"{len(qb_depth)} QB rows"
            )

        teams = qb_depth["team"].unique()
        latest_week_per_team = pd.DataFrame(
            {
                "team": teams,
                "week": [week] * len(teams),
            }
        )
        use_2025_format = True

    starting_qbs = []
    team_id_mapping = get_team_id_mapping()
    depth_field = "pos_rank" if use_2025_format else "depth_team"
    name_field = "player_name" if use_2025_format else "full_name"

    for _, team_week in latest_week_per_team.iterrows():
        if use_2025_format:
            team = team_week["team"]
            latest_week = team_week["week"]
            team_qbs = qb_depth[qb_depth["team"] == team].sort_values("pos_rank")
        else:
            team = team_week["club_code"]
            latest_week = team_week["week"]
            team_qbs = qb_depth[
                (qb_depth["club_code"] == team) & (qb_depth["week"] == latest_week)
            ].sort_values("depth_team")

        override_name = get_starter_override(season, str(team))
        qb_row = resolve_qb_starter_for_team(
            team=str(team),
            team_qbs=team_qbs,
            full_qb_depth=qb_depth,
            override_name=override_name,
            use_2025_format=use_2025_format,
        )
        if qb_row is None:
            continue

        qb = qb_row
        if override_name:
            rank_one = 1 if use_2025_format else "1"
            depth_starter = team_qbs[team_qbs[depth_field] == rank_one]
            depth_name = (
                str(depth_starter.iloc[0][name_field])
                if not depth_starter.empty
                else None
            )
            if depth_name and not _name_matches_starter(depth_name, override_name):
                print(f"  🔧 Override {team}: {depth_name} → {override_name}")

        is_injured = False
        injury_status = "Healthy"
        kickoff = get_game_kickoff(str(team), season, week)
        hours = hours_until_kickoff(kickoff)

        if not injuries.empty:
            qb_injuries = injuries[
                (injuries["gsis_id"] == qb["gsis_id"])
                & (injuries["week"] >= latest_week - 1)
            ]

            if not qb_injuries.empty:
                latest_injury = qb_injuries.sort_values("date_modified").iloc[-1]
                injury_status = latest_injury.get("report_status", "Unknown")

                promote = should_promote_backup(
                    injury_status, hours_to_kickoff=hours
                ) or injury_status in ["Out", "IR", "Doubtful"]
                if promote:
                    is_injured = True
                    print(
                        f"  ⚠️ {qb[name_field]} ({team}) - {injury_status}"
                        + (
                            f" (late escalate, {hours:.1f}h to KO)"
                            if hours is not None
                            and str(injury_status).lower() in {"questionable", "q"}
                            else ""
                        )
                    )

                    if use_2025_format:
                        backup = team_qbs[team_qbs["pos_rank"] == 2]
                    else:
                        backup = team_qbs[team_qbs["depth_team"] == "2"]

                    if not backup.empty:
                        qb = backup.iloc[0]
                        print(f"    ↳ Using backup: {qb[name_field]}")
                elif str(injury_status).lower() in {"questionable", "q"}:
                    print(
                        f"  ⚡ {qb[name_field]} ({team}) - Questionable "
                        f"(soft downgrade"
                        + (f", {hours:.1f}h to KO" if hours is not None else "")
                        + ")"
                    )

        team_id = team_id_mapping.get(team, 99)

        qb_data = {
            "name": qb[name_field],
            "team_id": team_id,
            "team_name": get_team_full_name(team),
            "team_abbr": team,
            "player_id": qb["gsis_id"],
            "depth": int(qb[depth_field]),
            "week": int(latest_week),
            "injury_status": injury_status,
            "is_backup": is_injured,
            "hours_to_kickoff": hours,
        }

        starting_qbs.append(qb_data)
        print(
            f"  ✅ {qb[name_field]} - {get_team_full_name(team)} (Depth: {qb[depth_field]})"
        )

    print(f"\n🎯 Found {len(starting_qbs)} starting QBs")
    return starting_qbs


def _name_matches_starter(row_name: str, target_name: str) -> bool:
    from app.services.etl.nfl.qb_tiers import normalize_qb_name_key

    return normalize_qb_name_key(row_name) == normalize_qb_name_key(target_name)


# predict_qb_passing_yards imported from qb_tiers (re-exported for callers)


def _run_qb_dynamic_core():
    """Create QB predictions using dynamic detection"""
    print("🚀 Dynamic QB Predictions - Heroku")
    print("=" * 50)

    season = get_nfl_season()
    week = get_current_nfl_week(season)

    print(f"📅 Season: {season}, Week: {week}")

    # Get dynamic starting QBs
    starting_qbs = get_dynamic_starting_qbs(season, week)

    if not starting_qbs:
        print("❌ No starting QBs found")
        return

    weekly_history = _load_weekly_qb_history(season)
    created_predictions = 0
    updated_predictions = 0

    for qb_data in starting_qbs:
        try:
            qb_name = qb_data["name"]
            team_id = qb_data["team_id"]
            team_name = qb_data["team_name"]
            team_abbr = qb_data["team_abbr"]
            player_id = qb_data["player_id"]
            is_backup = qb_data["is_backup"]
            injury_status = qb_data.get("injury_status") or "Healthy"
            hours = qb_data.get("hours_to_kickoff")

            # Get opponent team and scheduled kickoff
            opponent_abbr = get_team_opponent(team_abbr, season, week)
            game_date = _resolve_game_date(team_abbr, season, week)

            from app.services.etl.nfl.qb_late_availability import late_yard_adjustment
            from app.services.etl.nfl.qb_tiers import lookup_tier_base_yards

            tier_prediction = predict_qb_passing_yards(
                qb_name,
                season,
                week,
                is_backup,
                injury_status=None if is_backup else injury_status,
            )
            # Late availability: escalate Q cuts / heavier backup discount near KO
            raw_base = float(lookup_tier_base_yards(qb_name))
            late_yards, late_meta = late_yard_adjustment(
                base_yards=raw_base,
                injury_status=None if is_backup else injury_status,
                is_backup=is_backup,
                hours_to_kickoff=hours if isinstance(hours, (int, float)) else None,
            )
            tier_prediction["predicted_passing_yards"] = late_yards
            if late_meta.get("yard_cut"):
                half = (
                    float(
                        tier_prediction.get("prediction_interval_upper") or late_yards
                    )
                    - float(
                        tier_prediction.get("prediction_interval_lower") or late_yards
                    )
                ) / 2.0
                if half <= 0:
                    half = 35.0
                tier_prediction["prediction_interval_lower"] = round(
                    max(120.0, late_yards - half), 1
                )
                tier_prediction["prediction_interval_upper"] = round(
                    min(380.0, late_yards + half), 1
                )

            context = build_qb_prediction_context(
                qb_name=qb_name,
                player_id=str(player_id),
                team_abbr=team_abbr,
                opponent_abbr=opponent_abbr,
                season=season,
                week=week,
                weekly_history=weekly_history,
                injury_status=injury_status,
                is_backup=is_backup,
                hours_to_kickoff=(
                    float(hours) if isinstance(hours, (int, float)) else None
                ),
                static_tier_yards=float(tier_prediction["predicted_passing_yards"]),
            )
            context["late_availability"] = late_meta
            # If no prior games, anchor form features to this week's tier yards
            tier_yards = float(tier_prediction["predicted_passing_yards"])
            if not any(
                (
                    str(r.get("qb_player_id") or "") == str(player_id)
                    or str(r.get("qb_player_name") or "").lower() == qb_name.lower()
                )
                and int(r.get("week") or 0) < week
                for r in weekly_history
            ):
                context["rolling_yards_l3"] = tier_yards
                context["rolling_yards_l5"] = tier_yards
                context["season_avg_yards"] = tier_yards
            # Publish dynamic (form-blended) tier as the non-ML point estimate
            dynamic_tier = float(context.get("dynamic_tier_yards") or tier_yards)
            tier_prediction["predicted_passing_yards"] = dynamic_tier
            prediction = enrich_qb_prediction_for_write(
                tier_prediction,
                season=season,
                week=week,
                is_backup=is_backup,
                context=context,
            )

            # Create/update prediction
            existing_prediction = (
                db_session.query(QBPredictions)
                .filter_by(qb_player_id=player_id, season=season, week=week)
                .first()
            )

            write_kwargs = dict(
                predicted_passing_yards=prediction["predicted_passing_yards"],
                model_confidence=prediction["model_confidence"],
                prediction_method=prediction["prediction_method"],
                model_version=prediction.get("model_version"),
                feature_importance=prediction.get("feature_importance"),
                implied_team_total=context.get("implied_team_total"),
                prediction_interval_lower=prediction.get("prediction_interval_lower")
                or tier_prediction.get("prediction_interval_lower"),
                prediction_interval_upper=prediction.get("prediction_interval_upper")
                or tier_prediction.get("prediction_interval_upper"),
            )

            if not existing_prediction:
                new_prediction = QBPredictions(
                    qb_player_id=player_id,
                    qb_player_name=qb_name,
                    team_id=team_id,
                    team_name=team_name,
                    opponent_team_name=opponent_abbr,
                    game_date=game_date,
                    venue_name="TBD",
                    season=season,
                    week=week,
                    prediction_date=datetime.utcnow(),
                    **write_kwargs,
                )
                db_session.add(new_prediction)
                created_predictions += 1
                status = "🤕 Backup" if is_backup else "⭐ Starter"
                print(
                    f"  ➕ {status} {qb_name} vs {opponent_abbr}: {prediction['predicted_passing_yards']:.1f} yards"
                )
            else:
                # Update existing prediction
                existing_prediction.predicted_passing_yards = write_kwargs[
                    "predicted_passing_yards"
                ]
                existing_prediction.model_confidence = write_kwargs["model_confidence"]
                existing_prediction.prediction_method = write_kwargs[
                    "prediction_method"
                ]
                existing_prediction.model_version = write_kwargs["model_version"]
                existing_prediction.feature_importance = write_kwargs[
                    "feature_importance"
                ]
                if write_kwargs.get("implied_team_total") is not None:
                    existing_prediction.implied_team_total = write_kwargs[
                        "implied_team_total"
                    ]
                existing_prediction.opponent_team_name = (
                    opponent_abbr  # Update opponent name
                )
                existing_prediction.game_date = game_date
                existing_prediction.prediction_date = datetime.utcnow()
                updated_predictions += 1
                status = "🤕 Backup" if is_backup else "⭐ Starter"
                print(
                    f"  🔄 {status} {qb_name} vs {opponent_abbr}: {prediction['predicted_passing_yards']:.1f} yards"
                )

            db_session.commit()

        except Exception as e:
            print(f"  ❌ Error processing {qb_data['name']}: {e}")
            db_session.rollback()

    print(f"\n📊 DYNAMIC PREDICTIONS SUMMARY:")
    print(f"   ➕ Created Predictions: {created_predictions}")
    print(f"   🔄 Updated Predictions: {updated_predictions}")

    print(f"\n✅ Dynamic predictions complete!")


if __name__ == "__main__":
    from app.services.etl.nfl._db import init_session, close_session

    init_session()
    try:
        _run_qb_dynamic_core()
    finally:
        close_session()


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        _run_qb_dynamic_core()
        return {"status": "ok", "task": "nfl_qb_dynamic"}
    finally:
        close_session()
