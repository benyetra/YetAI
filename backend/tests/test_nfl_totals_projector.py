from app.services.etl.nfl.totals_projector import (
    TOTALS_EDGE_THRESHOLD,
    _align_scores,
    _project_totals_row,
    _totals_recommendation,
)


def test_align_scores_satisfies_total_and_margin_identities():
    margin = 4.0
    total = 48.0
    home_pts, away_pts = _align_scores(margin, total)
    assert abs((home_pts + away_pts) - total) < 1e-9
    assert abs((home_pts - away_pts) - margin) < 1e-9
    assert home_pts == 26.0
    assert away_pts == 22.0


def test_totals_recommendation_thresholds():
    edge, rec = _totals_recommendation(47.0, 43.0, threshold=TOTALS_EDGE_THRESHOLD)
    assert edge == 4.0
    assert rec == "OVER"

    edge, rec = _totals_recommendation(41.0, 45.0, threshold=TOTALS_EDGE_THRESHOLD)
    assert edge == -4.0
    assert rec == "UNDER"

    edge, rec = _totals_recommendation(45.0, 44.0, threshold=TOTALS_EDGE_THRESHOLD)
    assert rec == "NO_PLAY"

    edge, rec = _totals_recommendation(45.0, None)
    assert edge is None
    assert rec == "NO_PLAY"


def test_project_totals_row_aligns_scores():
    row = _project_totals_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        market_total=47.0,
        elos={"Kansas City Chiefs": 1550.0, "Baltimore Ravens": 1450.0},
        ppg_stats={
            "Kansas City Chiefs": (28.0, 20.0),
            "Baltimore Ravens": (24.0, 22.0),
        },
    )
    home = row["home_projected_score"]
    away = row["away_projected_score"]
    total = row["projected_total"]
    margin = row["factors"]["projected_margin"]
    assert abs((home + away) - total) < 1e-6
    assert abs((home - away) - margin) < 1e-6
