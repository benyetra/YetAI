from app.models.predictions_models import RecvYdsActuals, RecvYdsPredictions


def test_recv_yds_tablename_and_unique():
    assert RecvYdsPredictions.__tablename__ == "pred_recv_yds_predictions"
    assert RecvYdsActuals.__tablename__ == "pred_recv_yds_actuals"
    pred_cols = {c.name for c in RecvYdsPredictions.__table__.columns}
    for required in {
        "player_id",
        "player_name",
        "position",
        "team_name",
        "opponent_team_name",
        "season",
        "week",
        "game_date",
        "predicted_receiving_yards",
        "model_yards",
        "ou_line",
        "edge",
        "edge_percentage",
        "betting_recommendation",
        "confidence_score",
        "prediction_method",
        "features",
        "model_version",
    }:
        assert required in pred_cols
