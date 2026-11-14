from datetime import datetime, timedelta

import pytest

from app.services.fair_price import flags, lines
from app.services.fair_price.flags import Q

AT = datetime(2026, 11, 14, 20, 0)
M = "player_rebounds"


def q(book, line=6.5, o=-110, u=-110, age=1):
    return Q(book, line, o, u, AT - timedelta(minutes=age))


def test_ev_playable():
    assert flags.ev(0.5, 150) == pytest.approx(0.25)
    assert flags.playable_to(0.55, 0.02) == -117
    assert flags.ev(0.55, -117) == pytest.approx(0.02009, abs=1e-5)
    assert flags.playable_to(0.40, 0.02) == 155
    assert flags.playable_to(0.50, 0.02) == 104


def test_flagged_four_books():
    qs = [q("a", o=150, u=-180), q("b"), q("c"), q("d")]
    out = flags.evaluate_prop(
        qs, AT, M, None, flags.FlagRule(), AT + timedelta(minutes=10)
    )
    # a's over: the three others are 0.5 -> EV .25
    assert [(f.book, f.side) for f in out] == [("a", "o")]
    f = out[0]
    assert f.fair_prob == pytest.approx(0.5, abs=1e-9) and f.ev == pytest.approx(0.25)
    assert f.playable_to == 104 and f.n_books == 3
    assert f.expires_at == AT + timedelta(minutes=10)


def test_min_books_and_stale():
    assert not flags.evaluate_prop(
        [q("a", o=150), q("b"), q("c")], AT, M, None, flags.FlagRule()
    )
    stale = [q("a", o=150), q("b"), q("c"), q("d", age=31)]
    assert not flags.evaluate_prop(stale, AT, M, None, flags.FlagRule())
    out = flags.evaluate_prop(stale + [q("e")], AT, M, None, flags.FlagRule())
    assert [f.book for f in out] == ["a"] and out[0].n_books == 3


def test_pinnacle_counts_but_not_flagged():
    qs = [q("pinnacle", o=250, u=-300), q("a", o=150), q("b"), q("c")]
    out = flags.evaluate_prop(qs, AT, M, None, flags.FlagRule())
    assert all(f.book != "pinnacle" for f in out)
    assert out and out[0].n_books == 3  # a's consensus: pinnacle + b + c


def test_converted_line():
    qs = [q("a", o=150), q("b", line=7.5, o=-150, u=130), q("c"), q("d")]
    probs = flags.book_fair(qs, AT, flags.FlagRule(method="multiplicative"))
    p, n = flags.fair_at_line({"b": probs["b"]}, 6.5, M, None)
    assert n == 1 and p == pytest.approx(
        lines.convert(0.5798319, 7.5, 6.5, M), abs=1e-6
    )
    assert p > 0.5798319  # lower line -> over more likely
    # exactly one book at hand value on the same line: unchanged
    assert flags.fair_at_line({"b": [(6.5, 0.4)]}, 6.5, M, None) == (
        pytest.approx(0.4),
        1,
    )
    assert flags.fair_at_line({"b": [(9.5, 0.4)]}, 6.5, M, None) == (None, 0)


def test_closest_line_tiebreak():
    p, n = flags.fair_at_line({"b": [(5.5, 0.7), (7.5, 0.45)]}, 6.5, M, None)
    assert n == 1  # tie on distance: picks the 0.45 quote (nearest .5)
    assert p == pytest.approx(lines.convert(0.45, 7.5, 6.5, M))


def test_excluded_env(monkeypatch):
    monkeypatch.setenv("FAIR_PRICE_EXCLUDED_BOOKS", "b, c")
    rule = flags.default_rule()
    assert rule.excluded_books == frozenset({"b", "c"})
    qs = [q("a", o=150), q("b"), q("c"), q("d"), q("e")]
    assert not flags.evaluate_prop(qs, AT, M, None, rule)  # only d, e left
