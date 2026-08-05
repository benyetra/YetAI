from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _configure_bpp(
    monkeypatch,
    hits,
    *,
    projected_hits,
    projected_home_runs,
    matchup_home_run_probability,
    park_factor=1.0,
    weight=0.25,
):
    projection = SimpleNamespace(
        bpp_game_id=776345,
        averages_json={
            "hits": projected_hits,
            "homeRuns": projected_home_runs,
        },
    )
    matchup = SimpleNamespace(
        probs_json={"homeRunProbability": matchup_home_run_probability}
    )
    hitter_park_factor = SimpleNamespace(factors_json={"homeRuns": park_factor})

    monkeypatch.setattr(hits, "ballpark_pal_enabled", lambda: True)
    monkeypatch.setattr(hits, "bpp_hits_prior_weight", lambda: weight)
    monkeypatch.setattr(hits, "bpp_hr_prior_weight", lambda: weight)
    monkeypatch.setattr(
        hits.bpp_store, "load_player_proj", lambda *_args, **_kwargs: projection
    )
    monkeypatch.setattr(
        hits.bpp_store, "load_matchup", lambda *_args, **_kwargs: matchup
    )
    monkeypatch.setattr(
        hits.bpp_store,
        "load_hitter_park_factor",
        lambda *_args, **_kwargs: hitter_park_factor,
    )


def _apply_priors(hits, combined_score=2.0, homer_score=4.0):
    return hits.maybe_apply_bpp_hitter_priors(
        combined_score,
        homer_score,
        batter_id=42,
        pitcher_id=99,
        slate_date=date(2026, 8, 5),
        session=MagicMock(),
    )


def test_bpp_baseline_projections_leave_scores_unchanged(monkeypatch):
    from app.services.etl.mlb import hits

    _configure_bpp(
        monkeypatch,
        hits,
        projected_hits=1.0,
        projected_home_runs=0.15,
        matchup_home_run_probability=3.75,
    )

    combined_score, homer_score = _apply_priors(
        hits, combined_score=3.2, homer_score=5.4
    )

    assert combined_score == pytest.approx(3.2, abs=0.01)
    assert homer_score == pytest.approx(5.4, abs=0.01)


def test_bpp_above_baseline_projections_increase_scores(monkeypatch):
    from app.services.etl.mlb import hits

    _configure_bpp(
        monkeypatch,
        hits,
        projected_hits=1.4,
        projected_home_runs=0.25,
        matchup_home_run_probability=6.25,
    )

    combined_score, homer_score = _apply_priors(hits)

    assert combined_score > 2.0
    assert homer_score > 4.0


def test_bpp_extreme_projections_use_bounded_multipliers(monkeypatch):
    from app.services.etl.mlb import hits

    _configure_bpp(
        monkeypatch,
        hits,
        projected_hits=100.0,
        projected_home_runs=100.0,
        matchup_home_run_probability=100.0,
        weight=1.0,
    )

    combined_score, homer_score = _apply_priors(hits)

    assert combined_score == 3.0
    assert homer_score == 6.0


def test_bpp_baseline_projections_preserve_board_threshold_candidates(monkeypatch):
    from app.services.etl.mlb import hits

    _configure_bpp(
        monkeypatch,
        hits,
        projected_hits=1.0,
        projected_home_runs=0.15,
        matchup_home_run_probability=3.75,
    )

    combined_score, homer_score = _apply_priors(hits)

    assert combined_score >= 2.0
    assert homer_score >= 4.0


def test_bpp_hitter_scores_apply_hr_park_factor_and_load_context(monkeypatch):
    from app.services.etl.mlb import hits

    session = MagicMock()
    projection = SimpleNamespace(
        bpp_game_id=776345,
        averages_json={"hits": 1.0, "homeRuns": 0.15},
    )
    matchup = SimpleNamespace(probs_json={"homeRunProbability": 3.75})
    park_factor = SimpleNamespace(factors_json={"homeRuns": 1.2})
    calls = []

    monkeypatch.setattr(hits, "ballpark_pal_enabled", lambda: True)
    monkeypatch.setattr(hits, "bpp_hits_prior_weight", lambda: 0.25)
    monkeypatch.setattr(hits, "bpp_hr_prior_weight", lambda: 0.25)

    def load_player_proj(db, player_id, slate_date, role):
        calls.append(("projection", db, player_id, slate_date, role))
        return projection

    def load_matchup(db, batter_id, pitcher_id, slate_date):
        calls.append(("matchup", db, batter_id, pitcher_id, slate_date))
        return matchup

    def load_hitter_park_factor(db, player_id, slate_date, bpp_game_id):
        calls.append(("park", db, player_id, slate_date, bpp_game_id))
        return park_factor

    monkeypatch.setattr(hits.bpp_store, "load_player_proj", load_player_proj)
    monkeypatch.setattr(hits.bpp_store, "load_matchup", load_matchup)
    monkeypatch.setattr(
        hits.bpp_store, "load_hitter_park_factor", load_hitter_park_factor
    )

    combined_score, homer_score = hits.maybe_apply_bpp_hitter_priors(
        4.0,
        0.4,
        batter_id=42,
        pitcher_id=99,
        slate_date=date(2026, 8, 5),
        session=session,
    )

    assert combined_score == 4.0
    assert homer_score == 0.48
    assert calls == [
        ("projection", session, 42, date(2026, 8, 5), "batter"),
        ("matchup", session, 42, 99, date(2026, 8, 5)),
        ("park", session, 42, date(2026, 8, 5), 776345),
    ]


def test_bpp_hitter_scores_no_op_when_disabled(monkeypatch):
    from app.services.etl.mlb import hits

    monkeypatch.setattr(hits, "ballpark_pal_enabled", lambda: False)

    def unexpected_loader(*_args, **_kwargs):
        raise AssertionError("disabled integration must not load snapshots")

    monkeypatch.setattr(hits.bpp_store, "load_player_proj", unexpected_loader)

    assert hits.maybe_apply_bpp_hitter_priors(
        4.0,
        0.4,
        batter_id=42,
        pitcher_id=99,
        slate_date=date(2026, 8, 5),
        session=MagicMock(),
    ) == (4.0, 0.4)


def test_bpp_hitter_scores_soft_fail_on_loader_error(monkeypatch):
    from app.services.etl.mlb import hits

    monkeypatch.setattr(hits, "ballpark_pal_enabled", lambda: True)

    def fail_loader(*_args, **_kwargs):
        raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr(hits.bpp_store, "load_player_proj", fail_loader)

    assert hits.maybe_apply_bpp_hitter_priors(
        4.0,
        0.4,
        batter_id=42,
        pitcher_id=99,
        slate_date=date(2026, 8, 5),
        session=MagicMock(),
    ) == (4.0, 0.4)
