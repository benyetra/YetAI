def test_nfl_anytime_td_models_importable():
    from app.models.predictions_models import (
        NFLAnytimeTDActuals,
        NFLAnytimeTDPredictions,
        NFLDefenseScheme,
    )

    assert NFLDefenseScheme.__tablename__ == "pred_nfl_defense_scheme"
    assert NFLAnytimeTDPredictions.__tablename__ == "pred_nfl_anytime_td_predictions"
    assert NFLAnytimeTDActuals.__tablename__ == "pred_nfl_anytime_td_actuals"


def test_anytime_td_model_version_column_fits_gbm_tag():
    """Prod failure: hierarchical_v1_gbm_pos (23) truncated varchar(20)."""
    from app.models.predictions_models import NFLAnytimeTDPredictions
    from app.services.etl.nfl.anytime_td_calibration import MODEL_VERSION_GBM

    col = NFLAnytimeTDPredictions.__table__.c.model_version
    assert col.type.length >= len(MODEL_VERSION_GBM)
    assert len(MODEL_VERSION_GBM) > 20  # regression guard for the original limit
