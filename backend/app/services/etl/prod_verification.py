"""
Production ETL verification — DB row counts and API-shaped prediction checks.

Used by POST /api/admin/celery/verify-etl and scripts/prod_verify_etl.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import (
    AssistsProjections,
    BlowoutChances,
    DailyHRPredictions,
    GameProjections,
    Homer,
    KickerPredictions,
    ValueBet,
    NBASpreadProjections,
    NBATotalsProjections,
    WNBAGameLines,
    WNBAAssistsProjections,
    WNBAPointsProjections,
    WNBAReboundsProjections,
    WNBASpreadProjections,
    WNBATotalsProjections,
    NHLGoaliePredictions,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsPredictions,
    Pitcher,
    PointsProjections,
    PRAProjections,
    ProjectedHits,
    QBPredictions,
    StrikeoutProjections,
)
from app.services.etl.nba._espn import now_eastern

# NFL regular season roughly Sep–Feb (ET)
NFL_IN_SEASON_MONTHS = {9, 10, 11, 12, 1, 2}


def _sport_verdict(passed: bool, warnings: list[str]) -> str:
    if passed:
        return "verified" if not warnings else "verified_with_warnings"
    return "failed"


def verify_mlb() -> dict[str, Any]:
    today = now_eastern().date()
    warnings: list[str] = []
    db = SessionLocal()
    try:
        pitchers = db.query(Pitcher).count()
        k_proj = (
            db.query(StrikeoutProjections)
            .filter(StrikeoutProjections.date == today)
            .count()
        )
        games = db.query(GameProjections).filter(GameProjections.date == today).count()
        hits_today = db.query(ProjectedHits).filter(ProjectedHits.date == today).count()
        blowouts = db.query(BlowoutChances).count()
        homers = db.query(Homer).count()
        value_bets_today = db.query(ValueBet).filter(ValueBet.date == today).count()
        hr_ml_today = (
            db.query(DailyHRPredictions)
            .filter(DailyHRPredictions.date == today)
            .count()
        )
    finally:
        db.close()

    passed = pitchers > 0 and k_proj > 0
    if games <= 0:
        warnings.append("no game projections today (off-day or incomplete pipeline)")
    if hits_today <= 0:
        warnings.append("no projected hits today")
    if blowouts <= 0:
        warnings.append("pred_blowout_chances empty")
    if homers <= 0:
        warnings.append("pred_homer empty")

    return {
        "sport": "mlb",
        "date_et": str(today),
        "passed": passed,
        "status": _sport_verdict(passed, warnings),
        "counts": {
            "pred_pitcher": pitchers,
            "strikeout_projections_today": k_proj,
            "game_projections_today": games,
            "projected_hits_today": hits_today,
            "blowout_chances": blowouts,
            "homers": homers,
            "value_bets_today": value_bets_today,
            "daily_hr_ml_today": hr_ml_today,
        },
        "warnings": warnings,
    }


def verify_nba() -> dict[str, Any]:
    today = now_eastern().date()
    warnings: list[str] = []
    db = SessionLocal()
    try:
        points = (
            db.query(PointsProjections).filter(PointsProjections.date == today).count()
        )
        pra = db.query(PRAProjections).filter(PRAProjections.date == today).count()
        totals_today = (
            db.query(NBATotalsProjections)
            .filter(NBATotalsProjections.game_date == today)
            .count()
        )
        spreads_today = (
            db.query(NBASpreadProjections)
            .filter(NBASpreadProjections.game_date == today)
            .count()
        )
    finally:
        db.close()

    # Full-season gates (~20/10) are too strict for playoff nights (often 1 game).
    passed = points >= 8 and pra >= 5
    if totals_today == 0:
        warnings.append(
            "no totals projections today (off-day or totals_projector failed)"
        )
    if spreads_today == 0:
        warnings.append(
            "no spread projections today (off-day, missing game lines, or spread_projector failed)"
        )
    elif points >= 20 and pra < 10:
        warnings.append(
            f"pra below legacy threshold (pra={pra}, points={points}); "
            "passed with playoff-sized minimums (8/5)"
        )

    return {
        "sport": "nba",
        "date_et": str(today),
        "passed": passed,
        "status": _sport_verdict(passed, warnings),
        "counts": {
            "points_today": points,
            "pra_today": pra,
            "totals_today": totals_today,
            "spreads_today": spreads_today,
        },
        "warnings": warnings,
    }


def verify_nhl() -> dict[str, Any]:
    today = now_eastern().date()
    yesterday = today - timedelta(days=1)
    warnings: list[str] = []
    db = SessionLocal()
    try:
        goalie = (
            db.query(NHLGoaliePredictions)
            .filter(NHLGoaliePredictions.game_date == today)
            .count()
        )
        shots = (
            db.query(NHLPlayerShotsPredictions)
            .filter(NHLPlayerShotsPredictions.game_date == today)
            .count()
        )
        totals = (
            db.query(NHLTeamTotalsPredictions)
            .filter(NHLTeamTotalsPredictions.game_date == today)
            .count()
        )
    finally:
        db.close()

    passed = goalie > 0 and shots > 0 and totals > 0
    if not passed:
        warnings.append(
            f"today empty (goalie={goalie}, shots={shots}, totals={totals}); "
            f"yesterday ref={yesterday}. "
            "Enqueue run_nhl_update_pipeline (ODDS_API_KEY alone is not enough). "
            "NHL schedule uses ET; re-run after deploy if worker was on UTC 'tomorrow'."
        )

    return {
        "sport": "nhl",
        "date_et": str(today),
        "passed": passed,
        "status": _sport_verdict(passed, warnings),
        "counts": {
            "goalie_predictions_today": goalie,
            "player_shots_today": shots,
            "team_totals_today": totals,
        },
        "warnings": warnings,
    }


def verify_nfl(*, in_season: bool | None = None) -> dict[str, Any]:
    today = now_eastern().date()
    if in_season is None:
        in_season = now_eastern().month in NFL_IN_SEASON_MONTHS

    warnings: list[str] = []
    db = SessionLocal()
    try:
        qb = (
            db.query(QBPredictions)
            .filter(QBPredictions.game_date >= today - timedelta(days=today.weekday()))
            .count()
        )
        kickers = (
            db.query(KickerPredictions)
            .filter(
                KickerPredictions.game_date >= today - timedelta(days=today.weekday())
            )
            .count()
        )
        qb_master = db.query(QBPredictions).count()
        kicker_master = db.query(KickerPredictions).count()
    finally:
        db.close()

    if not in_season:
        passed = True
        warnings.append(
            "off-season: prediction tables may be empty; verify orchestrator via enqueue only"
        )
    else:
        passed = qb > 0 and kickers > 0
        if not passed:
            warnings.append("in-season but no QB/kicker predictions this week")

    return {
        "sport": "nfl",
        "date_et": str(today),
        "in_season": in_season,
        "passed": passed,
        "status": _sport_verdict(passed, warnings),
        "counts": {
            "qb_predictions_this_week": qb,
            "kicker_predictions_this_week": kickers,
            "qb_predictions_all": qb_master,
            "kicker_predictions_all": kicker_master,
        },
        "warnings": warnings,
    }


def _wnba_in_season(today: date) -> bool:
    return date(today.year, 5, 1) <= today <= date(today.year, 10, 31)


def verify_wnba() -> dict[str, Any]:
    today = now_eastern().date()
    in_season = _wnba_in_season(today)
    warnings: list[str] = []
    db = SessionLocal()
    try:
        game_lines = (
            db.query(WNBAGameLines).filter(WNBAGameLines.game_date == today).count()
        )
        totals = (
            db.query(WNBATotalsProjections)
            .filter(WNBATotalsProjections.game_date == today)
            .count()
        )
        spreads = (
            db.query(WNBASpreadProjections)
            .filter(WNBASpreadProjections.game_date == today)
            .count()
        )
        points = (
            db.query(WNBAPointsProjections)
            .filter(WNBAPointsProjections.date == today)
            .count()
        )
        assists = (
            db.query(WNBAAssistsProjections)
            .filter(WNBAAssistsProjections.date == today)
            .count()
        )
        rebounds = (
            db.query(WNBAReboundsProjections)
            .filter(WNBAReboundsProjections.date == today)
            .count()
        )
    finally:
        db.close()

    if not in_season:
        passed = True
        warnings.append(
            "off-season (May–Oct ET): tables may be empty; enqueue "
            "run_wnba_update_pipeline to refresh when season starts"
        )
    else:
        passed = game_lines > 0 and totals > 0 and spreads > 0 and points >= 8
        if game_lines <= 0:
            warnings.append(
                "no game lines today — enqueue WNBA pipeline or run update_game_lines "
                "(requires ODDS_API_KEY)"
            )
        if points < 8:
            warnings.append(
                "few player prop rows today — run full pipeline after game lines + roster"
            )

    return {
        "sport": "wnba",
        "date_et": str(today),
        "in_season": in_season,
        "passed": passed,
        "status": _sport_verdict(passed, warnings),
        "counts": {
            "game_lines_today": game_lines,
            "totals_today": totals,
            "spreads_today": spreads,
            "points_today": points,
            "assists_today": assists,
            "rebounds_today": rebounds,
        },
        "warnings": warnings,
    }


def verify_all_sports() -> dict[str, Any]:
    sports = [verify_mlb(), verify_nba(), verify_wnba(), verify_nhl(), verify_nfl()]
    all_passed = all(s["passed"] for s in sports)
    any_failed = any(s["status"] == "failed" for s in sports)
    return {
        "overall": (
            "verified" if all_passed else ("failed" if any_failed else "partial")
        ),
        "sports": sports,
        "summary": {s["sport"]: s["status"] for s in sports},
    }


def prediction_api_counts() -> dict[str, Any]:
    """Mirror /api/v1/predictions/* row counts for today's ET date."""
    today = now_eastern().date()
    mlb = verify_mlb()
    nba = verify_nba()
    wnba = verify_wnba()
    nhl = verify_nhl()
    nfl = verify_nfl()
    return {
        "date_et": str(today),
        "mlb": {
            "strikeout_projections": mlb["counts"]["strikeout_projections_today"],
            "projected_hits": mlb["counts"]["projected_hits_today"],
        },
        "nba": {
            "totals": nba["counts"]["totals_today"],
            "points": nba["counts"]["points_today"],
        },
        "wnba": {
            "totals": wnba["counts"]["totals_today"],
            "spreads": wnba["counts"]["spreads_today"],
            "points": wnba["counts"]["points_today"],
        },
        "nhl": {
            "goalie_predictions": nhl["counts"]["goalie_predictions_today"],
            "player_shots": nhl["counts"]["player_shots_today"],
            "team_totals": nhl["counts"]["team_totals_today"],
        },
        "nfl": {
            "qb_predictions": nfl["counts"]["qb_predictions_this_week"],
            "kicker_predictions": nfl["counts"]["kicker_predictions_this_week"],
        },
    }
