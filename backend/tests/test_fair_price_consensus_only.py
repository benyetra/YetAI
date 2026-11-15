"""Consensus-only books (novig, prophetx): in the consensus, never flagged or offered."""

import math
from datetime import datetime, timedelta

import pytest

from app.services import odds_math
from app.services.etl.nba import _fanduel_lines
from app.services.fair_price import backtest, flags
from app.services.fair_price.flags import Q

AT = datetime(2026, 11, 14, 20, 0)
M = "player_rebounds"
MULT = {"method": "multiplicative"}


def q(book, o=-110, u=-110, line=6.5):
    return Q(book, line, o, u, AT - timedelta(minutes=1))


def test_env_parsing(monkeypatch):
    monkeypatch.delenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", raising=False)
    assert odds_math.consensus_only_books() == {"novig", "prophetx"}
    monkeypatch.setenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", "")
    assert odds_math.consensus_only_books() == frozenset()
    monkeypatch.setenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", " NoVig , x ")
    assert odds_math.consensus_only_books() == {"novig", "x"}
    assert flags.default_rule().consensus_only == {"novig", "x"}


def test_prop_books_match_backfill():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "bf", path / "odds_history_backfill.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    books = _fanduel_lines.PROP_BOOKS.split(",")
    assert len(books) == 10
    assert set(books) == set(mod.DEFAULT_BOOKS.split(","))


def test_best_quote_skips_consensus_only_but_it_moves_center(monkeypatch):
    monkeypatch.delenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", raising=False)
    qs = [
        odds_math.Quote("fanduel", 6.5, -110, -110),
        odds_math.Quote("draftkings", 6.5, -115, -105),
        odds_math.Quote("novig", 6.5, 150, -180),  # best over price, never offered
    ]
    b = odds_math.best_quote(qs, "o")
    assert b.book == "fanduel" and b.price == -110
    without = odds_math.consensus_center(qs[:2], 3.0)
    assert odds_math.consensus_center(qs, 3.0) != without
    # opting out of the default offers the exchange again
    monkeypatch.setenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", "")
    assert odds_math.best_quote(qs, "o").book == "novig"


def _hand_fair():
    # novig -200/+170 de-vigs to 9/14 over (multiplicative): logit ln(9/5); with two 0.5 books
    # the equal log pool is sigmoid(ln(9/5)/3)
    return 1 / (1 + math.exp(-math.log(9 / 5) / 3))


@pytest.mark.parametrize("fn", [flags.evaluate_prop, backtest.fast_prop_flags])
def test_consensus_only_informs_but_is_never_flagged(fn):
    rule = flags.FlagRule(consensus_only=frozenset({"novig"}), **MULT)
    qs = [q("a", o=100, u=-120), q("b"), q("c"), q("novig", o=-200, u=170)]
    out = fn(qs, AT, M, None, rule)
    # a's others: b, c at .5 and novig at 9/14 -> n=3 and the hand-computed pool
    assert [(f.book, f.side) for f in out] == [("a", "o")]
    f = out[0]
    assert f.n_books == 3 and f.fair_prob == pytest.approx(_hand_fair())
    assert f.ev == pytest.approx(_hand_fair() * 2 - 1)
    # without novig only 2 others: below min_books
    assert fn(qs[:3], AT, M, None, rule) == []
    # novig at a price that clears 5% is flagged only when the rule lets it be a candidate
    cheap = [q("a"), q("b"), q("c"), q("novig", o=300, u=-400)]
    assert "novig" not in {x.book for x in fn(cheap, AT, M, None, rule)}
    plain = fn(cheap, AT, M, None, flags.FlagRule(**MULT))
    assert ("novig", "o") in {(x.book, x.side) for x in plain}


def test_default_flagrule_unchanged():
    assert flags.FlagRule().consensus_only == frozenset()
