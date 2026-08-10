from app.tasks.etl_pipeline import NFL_PHASES

EXPECTED_PHASE_ORDER = ["actuals", "game_lines", "game_projections", "predictions"]
SEED_ELO_TASK = "app.tasks.etl_pipeline.nfl.seed_elo_history"
STORE_GAME_ACTUALS_TASK = "app.tasks.etl_pipeline.nfl.store_game_actuals"


def test_nfl_phases_order():
    names = [phase for phase, _ in NFL_PHASES]
    assert names == EXPECTED_PHASE_ORDER


def test_nfl_phases_exclude_seed_elo_history():
    flat = [t.name for _, tasks in NFL_PHASES for t in tasks]
    assert SEED_ELO_TASK not in flat


def test_nfl_phases_actuals_include_store_game_actuals():
    actuals_tasks = next(tasks for phase, tasks in NFL_PHASES if phase == "actuals")
    actuals_names = [t.name for t in actuals_tasks]
    assert STORE_GAME_ACTUALS_TASK in actuals_names


def test_nfl_phases_include_game_board():
    names = [phase for phase, _ in NFL_PHASES]
    assert "game_lines" in names
    assert "game_projections" in names
    flat = [t.name for _, tasks in NFL_PHASES for t in tasks]
    assert "app.tasks.etl_pipeline.nfl.update_game_lines" in flat
    assert "app.tasks.etl_pipeline.nfl.spread_projector" in flat
    assert "app.tasks.etl_pipeline.nfl.totals_projector" in flat
    assert STORE_GAME_ACTUALS_TASK in flat
