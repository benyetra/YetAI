from app.services.etl.nfl.recv_yds_betting import (
    RECV_YDS_MARKET,
    attach_recv_betting,
    clear_betting_fields,
    generate_betting_recommendation,
    get_best_line,
    normalize_player_name,
)


def test_market_key_is_reception_yds():
    assert RECV_YDS_MARKET == "player_reception_yds"


def test_normalize_player_name_aliases():
    assert normalize_player_name("AJ Brown") == "A.J. Brown"


def test_clear_betting_fields_nulls_market_columns():
    cleared = clear_betting_fields()
    assert cleared["ou_line"] is None
    assert cleared["edge"] is None
    assert cleared["edge_percentage"] is None
    assert cleared["betting_recommendation"] is None
    assert cleared["over_odds"] is None
    assert cleared["under_odds"] is None


def test_generate_recommendation_pass_on_thin_edge():
    rec = generate_betting_recommendation(
        prediction=85.0, ou_line=80.0, confidence=0.72
    )
    # edge = 5 yards → 6.25% < 7% → PASS
    assert rec["recommendation"] == "PASS"


def test_generate_recommendation_over_on_strong_edge():
    rec = generate_betting_recommendation(
        prediction=92.0, ou_line=80.0, confidence=0.80
    )
    # 15% edge → OVER LARGE
    assert rec["recommendation"] == "OVER"
    assert rec["bet_size"] == "LARGE"


def test_attach_recv_betting_fail_closed_without_line():
    assert (
        attach_recv_betting(model_yards=70.0, confidence_score=0.72, player_lines={})
        is None
    )


def test_attach_recv_betting_soft_anchors_and_sets_edge():
    lines = {
        "FanDuel": {
            "over": {"line": 80.0, "odds": -110},
            "under": {"line": 80.0, "odds": -110},
        }
    }
    out = attach_recv_betting(
        model_yards=100.0, confidence_score=0.80, player_lines=lines, anchor_alpha=0.25
    )
    assert out is not None
    assert out["ou_line"] == 80.0
    assert out["predicted_receiving_yards"] == 85.0
    assert out["prediction_method"] == "soft_anchor"
    assert out["edge"] == 5.0
    assert out["predicted_receiving_yards"] != out["ou_line"]


def test_get_best_line_picks_books():
    best = get_best_line(
        {
            "FanDuel": {
                "over": {"line": 70.5, "odds": -115},
                "under": {"line": 70.5, "odds": -105},
            },
            "DraftKings": {
                "over": {"line": 71.5, "odds": -110},
                "under": {"line": 71.5, "odds": -110},
            },
        }
    )
    assert best["over"]["line"] == 71.5
    assert best["under"]["line"] == 70.5
