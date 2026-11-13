from app.services.auto_pick.diagnostics import summarize_drop_reasons


def test_summarize_drop_reasons():
    dropped = {
        "e1": "below_threshold:58.0",
        "e2": "below_threshold:61.2",
        "e3": "odds_out_of_bounds:500",
    }
    assert summarize_drop_reasons(dropped) == {
        "below_threshold": 2,
        "odds_out_of_bounds": 1,
    }


def test_summarize_drop_reasons_reads_counts_shape():
    dropped = {
        "counts": {"below_floor": 4, "no_play": 1},
        "top_rejected": [{"event_id": "e1", "reason": "below_floor"}],
    }
    assert summarize_drop_reasons(dropped) == {"below_floor": 4, "no_play": 1}


def test_projection_counts_cover_all_leagues(sqlite_db):
    from datetime import date

    from app.services.auto_pick.diagnostics import projection_counts_for_day

    counts = projection_counts_for_day(sqlite_db, date(2026, 5, 22))
    for key in (
        "nba_spread_projections",
        "wnba_totals_projections",
        "nfl_qb_passing_with_line",
        "nfl_spread_projections",
        "nfl_totals_projections",
        "nfl_receiving_yards_with_line",
        "nhl_totals_projections",
        "nhl_goalie_saves_with_line",
        "mlb_strikeout_with_line",
        "mlb_game_projections",
    ):
        assert counts[key] == 0
