def test_nfl_anytime_td_models_importable():
    from app.models.predictions_models import (
        NFLAnytimeTDActuals,
        NFLAnytimeTDPredictions,
        NFLDefenseScheme,
    )

    assert NFLDefenseScheme.__tablename__ == "pred_nfl_defense_scheme"
    assert NFLAnytimeTDPredictions.__tablename__ == "pred_nfl_anytime_td_predictions"
    assert NFLAnytimeTDActuals.__tablename__ == "pred_nfl_anytime_td_actuals"
