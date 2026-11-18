import asyncio

from app.models.predictions_models import PointsProjections
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.sources.player_prop_source import PlayerPropSource
from tests.auto_pick.test_sources_nba import AWAY, DAY, RANGE, _gl


def _cands(db):
    p = PlayerPropCandidateProvider(PlayerPropSource(db))
    return {
        c.projection_metadata["player"]: c for c in asyncio.run(p.get_candidates(RANGE))
    }


def test_best_quote_replaces_fanduel_and_falls_back(sqlite_db):
    _gl(sqlite_db)
    common = dict(date=DAY, opponent_team_name=AWAY, projected_points=29.0)
    sqlite_db.add_all(
        [
            PointsProjections(
                player_id=1,
                player_name="Has Best",
                fanduel_line=26.5,
                fanduel_over_under="o",
                fanduel_price=-125,
                best_book="draftkings",
                best_line=25.5,
                best_price=-105,
                **common,
            ),
            PointsProjections(
                player_id=2,
                player_name="Fanduel Only",
                fanduel_line=27.5,
                fanduel_over_under="o",
                fanduel_price=-115,
                **common,
            ),
            PointsProjections(  # neither price -> skipped
                player_id=3,
                player_name="No Price",
                fanduel_line=27.5,
                fanduel_over_under="o",
                **common,
            ),
        ]
    )
    sqlite_db.commit()
    c = _cands(sqlite_db)
    assert set(c) == {"Has Best", "Fanduel Only"}
    best = c["Has Best"]
    assert (best.market_line, best.market_odds) == (25.5, -105)
    assert best.projection_metadata["book"] == "draftkings"
    assert best.selection == "Has Best OVER 25.5 points"
    fd = c["Fanduel Only"]
    assert (fd.market_line, fd.market_odds) == (27.5, -115)
    assert fd.projection_metadata["book"] == "fanduel"


def test_fair_prob_and_projected_at_reach_the_candidate(sqlite_db):
    from datetime import datetime

    _gl(sqlite_db)
    ts = datetime(2026, 1, 15, 17, 0)
    common = dict(
        date=DAY, opponent_team_name=AWAY, projected_points=29.0, projected_at=ts
    )
    fd = dict(fanduel_line=26.5, fanduel_over_under="o", fanduel_price=-125)
    sqlite_db.add_all(
        [
            PointsProjections(
                player_id=1,
                player_name="Has Fair",
                best_book="draftkings",
                best_line=25.5,
                best_price=-105,
                best_fair_prob=0.55,
                best_ev=0.05,
                best_quoted_at=datetime(2026, 1, 15, 8, 0),
                **fd,
                **common,
            ),
            PointsProjections(player_id=2, player_name="Fd Only", **fd, **common),
        ]
    )
    sqlite_db.commit()
    c = _cands(sqlite_db)
    md = c["Has Fair"].projection_metadata
    assert md["fair_prob"] == 0.55
    assert md["projected_at"] == ts == md["generated_at"]
    assert md["quoted_at"] == datetime(2026, 1, 15, 8, 0)  # the quote's own time
    # a FanDuel-only price is never paired with a consensus probability
    assert c["Fd Only"].projection_metadata["fair_prob"] is None
    assert c["Fd Only"].projection_metadata["projected_at"] == ts
    assert c["Fd Only"].projection_metadata["quoted_at"] is None


def test_wnba_candidate_has_no_projected_at_key():
    from types import SimpleNamespace

    row = SimpleNamespace(
        date=DAY,
        opponent_team_name=AWAY,
        player_id=1,
        player_name="W",
        projected_points=20.0,
        market_line=18.5,
        fanduel_price=-110,
        fanduel_over_under="o",
        model_version=None,
        created_at=None,
        confidence_score=None,
    )
    assert not hasattr(row, "projected_at")

    class _Q:
        def filter(self, *_):
            return self

        def all(self):
            return [row]

    class _Db:
        def begin_nested(self):
            from contextlib import nullcontext

            return nullcontext()

        def query(self, _):
            return _Q()

    from app.services.auto_pick.sources import _basketball as bb

    class _M:
        date = DAY

    gl = SimpleNamespace(
        home_team_name="H", away_team_name=AWAY, odds_api_event_id="e", game_time=None
    )
    orig = bb._lines
    bb._lines = lambda *_: [gl]
    try:
        rows = bb.prop_rows(
            _Db(),
            [(_M, "points", "projected_points", "market_line", "created_at")],
            object,
            "WNBA",
            RANGE,
            lambda r: "over",
        )
    finally:
        bb._lines = orig
    assert "projected_at" not in rows[0]


def _apply_with_best(monkeypatch, row, best, quotes=True):
    from app.services.etl.nba import _fanduel_lines as fdl

    monkeypatch.setattr(
        fdl, "fetch_fanduel_prop_for_player", lambda *a, **k: (None, None, None)
    )
    monkeypatch.setattr(fdl, "get_event_id_for_game", lambda *a: "e1")
    monkeypatch.setattr(fdl, "prop_quotes", lambda *a: [object()] if quotes else [])
    monkeypatch.setattr(fdl.odds_math, "best_quote", lambda *a, **k: best)
    fdl.apply_fanduel_to_projection(
        row,
        team_name="A",
        opponent_team_name="B",
        player_name="P",
        market="player_points",
        projection=29.0,
    )


def test_apply_stores_fair_prob_and_ev_then_clears_without_fresh_quote(monkeypatch):
    from types import SimpleNamespace

    from app.services.odds_math import BestQuote

    row = SimpleNamespace(fanduel_line=26.5, fanduel_over_under="o", fanduel_price=-120)
    _apply_with_best(monkeypatch, row, BestQuote("dk", 25.5, -105, 0.55, 0.05))
    assert (row.best_fair_prob, row.best_ev) == (0.55, 0.05)
    assert row.best_quoted_at == row.projected_at
    quoted = row.best_quoted_at
    # rerun finds no quotes: the quote keeps its pair and its old quote time, so it never
    # looks fresh (projected_at moves on, best_quoted_at does not)
    _apply_with_best(monkeypatch, row, None, quotes=False)
    assert (row.best_price, row.best_fair_prob, row.best_ev) == (-105, 0.55, 0.05)
    assert row.best_quoted_at == quoted and row.projected_at >= quoted
    # a quote run that finds no best quote clears the whole quote
    _apply_with_best(monkeypatch, row, None)
    assert (row.best_price, row.best_fair_prob, row.best_quoted_at) == (
        None,
        None,
        None,
    )


def test_apply_side_flip_clears_fair_prob(monkeypatch):
    from types import SimpleNamespace

    row = SimpleNamespace(
        fanduel_line=31.5,
        fanduel_over_under="o",  # projection 29 is now below the line: under
        fanduel_price=-120,
        best_book="dk",
        best_line=25.5,
        best_price=-105,
        best_fair_prob=0.55,
        best_ev=0.05,
    )
    _apply_with_best(monkeypatch, row, None, quotes=False)
    assert row.best_price is None
    assert (row.best_fair_prob, row.best_ev, row.best_quoted_at) == (None, None, None)
