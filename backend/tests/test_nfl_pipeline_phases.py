from app.tasks.etl_pipeline import NFL_PHASES


def test_nfl_phases_include_game_board():
    names = [phase for phase, _ in NFL_PHASES]
    assert "game_lines" in names
    assert "game_projections" in names
    flat = [t.name for _, tasks in NFL_PHASES for t in tasks]
    assert "app.tasks.etl_pipeline.nfl.update_game_lines" in flat
    assert "app.tasks.etl_pipeline.nfl.spread_projector" in flat
    assert "app.tasks.etl_pipeline.nfl.totals_projector" in flat
    assert "app.tasks.etl_pipeline.nfl.store_game_actuals" in flat
