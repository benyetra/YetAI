from app.services.etl.wnba._shooting_metrics import (
    effective_fg_pct,
    enrich_boxscore_row,
    true_shooting_pct,
)


def test_effective_fg_pct_from_makes_and_attempts():
    # 10 FGM with 4 threes on 20 FGA → (10 + 2) / 20 = 0.60
    assert (
        effective_fg_pct(
            field_goals_made=10, three_pt_made=4, fg_attempts=20, stored=None
        )
        == 0.6
    )


def test_effective_fg_pct_prefers_stored():
    assert (
        effective_fg_pct(
            field_goals_made=1, three_pt_made=0, fg_attempts=10, stored=0.55
        )
        == 0.55
    )


def test_true_shooting_pct_from_box_score():
    # 20 pts on 15 FGA + 5 FTA → 20 / (2 * (15 + 2.2)) ≈ 0.581
    ts = true_shooting_pct(points=20, fg_attempts=15, ft_attempts=5, stored=None)
    assert ts is not None
    assert abs(ts - 0.581) < 0.01


def test_enrich_boxscore_row_adds_derived_columns():
    row = enrich_boxscore_row(
        {
            "points": 20,
            "field_goals_made": 8,
            "three_pt_made": 2,
            "fg_attempts": 16,
            "ft_attempts": 4,
        }
    )
    assert row["effective_field_goal_percentage"] == (8 + 1) / 16
    assert row["true_shooting_percentage"] is not None


def test_enrich_boxscore_row_sets_null_shooting_when_no_attempts():
    row = enrich_boxscore_row({"points": 0, "fg_attempts": 0, "ft_attempts": 0})
    assert "effective_field_goal_percentage" in row
    assert "true_shooting_percentage" in row
    assert row["effective_field_goal_percentage"] is None
    assert row["true_shooting_percentage"] is None
