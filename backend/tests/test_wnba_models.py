"""Smoke test: every WNBA SQLAlchemy class is importable and points at the right table."""

import pytest


def test_wnba_models_importable():
    from app.models.predictions_models import (
        WNBATeamRoster,
        WNBATeamOffenseStats,
        WNBATeamDefenseStats,
        WNBARecentGames,
        WNBAPlayerInjuryStatus,
        WNBAGameLines,
        WNBATotalsProjections,
        WNBATotalsActuals,
        WNBATeamPaceEfficiency,
        WNBATotalsAccuracy,
        WNBASpreadProjections,
        WNBASpreadActuals,
        WNBASpreadAccuracy,
        WNBATodayActivePlayers,
        WNBAPointsProjections,
        WNBAPointsActuals,
        WNBAAssistsProjections,
        WNBAAssistsActuals,
        WNBAReboundsProjections,
        WNBAReboundsActuals,
        WNBAThreePtMadeProjections,
        WNBAThreePtMadeActuals,
        WNBAPRAProjections,
        WNBAPRAActuals,
    )

    assert WNBATeamRoster.__tablename__ == "pred_wnba_team_roster"
    assert WNBAGameLines.__tablename__ == "pred_wnba_game_lines"
    assert WNBASpreadProjections.__tablename__ == "pred_wnba_spread_projections"
    assert WNBAPointsProjections.__tablename__ == "pred_wnba_points_projections"
    assert (
        WNBAThreePtMadeProjections.__tablename__
        == "pred_wnba_three_pt_made_projections"
    )
    assert WNBAPRAProjections.__tablename__ == "pred_wnba_pra_projections"
