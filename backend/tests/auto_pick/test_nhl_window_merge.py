"""NHL window row sets pair each projection with the actual from its own game date."""

from datetime import date

from app.models.predictions_models import NHLGoalieActuals, NHLGoaliePredictions
from app.services.nhl_accuracy_service import _nhl_rows


def test_goalie_actual_is_matched_by_game_date(sqlite_db):
    d1, d2 = date(2026, 11, 1), date(2026, 11, 3)
    for d, line, actual in ((d1, 25.5, 30), (d2, 25.5, 20)):
        sqlite_db.add(
            NHLGoaliePredictions(
                game_date=d,
                goalie_id=7,
                goalie_name="G",
                team_id=1,
                team_name="T",
                opponent_team_id=2,
                opponent_team_name="O",
                predicted_saves=28.0,
                predicted_shots_against=30.0,
                predicted_save_pct=0.9,
                saves_line=line,
                betting_recommendation="OVER",
            )
        )
        sqlite_db.add(
            NHLGoalieActuals(
                game_id=int(d.strftime("%d")),
                game_date=d,
                goalie_id=7,
                goalie_name="G",
                team_name="T",
                opponent_team_name="O",
                actual_saves=actual,
                actual_shots_against=actual + 2,
                actual_save_pct=0.9,
                actual_goals_against=2,
            )
        )
    sqlite_db.commit()

    rows = _nhl_rows(sqlite_db, start=d1, end=d2)["goalie"]
    assert sorted(r["actual_saves"] for r in rows) == [20, 30]
