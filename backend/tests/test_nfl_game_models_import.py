def test_nfl_game_models_importable():
    from app.models.predictions_models import (
        NFLGameLines,
        NFLSpreadProjections,
        NFLTotalsProjections,
        NFLSpreadActuals,
        NFLTotalsActuals,
        NFLTeamElo,
    )

    assert NFLGameLines.__tablename__ == "pred_nfl_game_lines"
    assert NFLTeamElo.__tablename__ == "pred_nfl_team_elo"
