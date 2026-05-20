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
    GameProjections,
    Homer,
    KickerPredictions,
    NBATotalsProjections,
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
    finally:
        db.close()

    passed = points >= 20 and pra >= 10
    if totals_today == 0:
        warnings.append(
            "no totals projections today (off-day or totals_projector failed)"
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
            f"yesterday ref={yesterday}"
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


def verify_all_sports() -> dict[str, Any]:
    sports = [verify_mlb(), verify_nba(), verify_nhl(), verify_nfl()]
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
