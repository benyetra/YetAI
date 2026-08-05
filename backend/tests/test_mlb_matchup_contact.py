from datetime import date
from unittest.mock import MagicMock

from app.services.etl.mlb.profiles.matchup_contact import contact_matchup_score


def test_contact_matchup_score_positive_edge():
    store = MagicMock()
    batter = MagicMock()
    batter.profile = {
        "xwoba_by_pitch": {"FF": 0.380},
        "iso_by_pitch": {"FF": 0.200},
        "barrel_rate_by_pitch": {"FF": 0.12},
    }
    batter.profile_version = "mlb-profile-v1"
    pitcher = MagicMock()
    pitcher.profile = {"usage": {"FF": 1.0}}
    pitcher.n_pitches = 300
    pitcher.pitcher_id = 101
    store.get_batter.return_value = batter
    store.get_pitcher.return_value = pitcher
    store.db = None

    delta, version = contact_matchup_score(store, 201, 101, "R", date(2024, 6, 1))
    assert delta > 0
    assert version == "mlb-profile-v1"
