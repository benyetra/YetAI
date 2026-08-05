from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_bpp_hitter_scores_blend_and_apply_hr_signals(monkeypatch):
    from app.services.etl.mlb import hits

    assert hasattr(hits, "maybe_apply_bpp_hitter_priors")

    session = MagicMock()
    projection = SimpleNamespace(
        bpp_game_id=776345,
        averages_json={"hits": 2.0, "homeRuns": 0.2},
    )
    matchup = SimpleNamespace(probs_json={"homeRunProbability": 5.0})
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

    assert combined_score == 3.5
    assert homer_score == 0.38
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
