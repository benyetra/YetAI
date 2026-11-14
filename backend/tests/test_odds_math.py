"""Price maths with hand-computed cases (app/services/odds_math.py)."""

from pytest import approx

from app.services.odds_math import (
    Quote,
    american_to_prob,
    best_quote,
    breakeven_rate,
    median_price,
    prob_to_american,
    devig,
    fair_median,
    line_clv,
    prob_clv,
    units_for_result,
    units_won,
)


def test_implied_probability():
    assert american_to_prob(-110) == approx(110 / 210)  # 0.5238
    assert american_to_prob(+150) == approx(0.4)  # 100 / 250
    assert american_to_prob(-200) == approx(2 / 3)
    assert american_to_prob(+100) == approx(0.5)
    assert breakeven_rate(-138) == approx(138 / 238)  # 0.5798: the -138 median price


def test_units_won_and_lost():
    assert units_won(-110, True) == approx(100 / 110)  # 0.909
    assert units_won(+150, True) == approx(1.5)
    assert units_won(-200, True) == approx(0.5)
    assert units_won(+150, False) == -1.0
    # Graded results: pushes and no-plays are 0; no price means -110.
    assert units_for_result("hit", None) == approx(100 / 110)
    assert units_for_result("hit", -125) == approx(0.8)
    assert units_for_result("miss", -125) == -1.0
    assert units_for_result("push", -125) == 0.0
    # 10 hits and 10 misses at -110 lose 0.909 units; at +100 they break even.
    rows = ["hit"] * 10 + ["miss"] * 10
    assert sum(units_for_result(r, -110) for r in rows) == approx(10 / 1.1 - 10)
    assert sum(units_for_result(r, 100) for r in rows) == approx(0.0)


def test_devig_and_fair_median():
    assert devig(-110, -110) == approx((0.5, 0.5))
    # -120 / +100: 0.54545 and 0.5 normalised by 1.04545.
    po, pu = devig(-120, +100)
    assert po == approx(0.521739, abs=1e-6)
    assert pu == approx(0.478261, abs=1e-6)
    assert fair_median(24.5, -110, -110, 6.5) == approx(24.5)
    # Over favoured -> the median sits above the line.
    assert fair_median(24.5, -120, +100, 6.5) > 24.5


def test_best_price_same_line_is_highest_price():
    q = [
        Quote("fanduel", 24.5, -115, -105),
        Quote("draftkings", 24.5, -105, -115),
        Quote("betmgm", 24.5, -110, -110),
    ]
    over = best_quote(q, "o", projection=26.0, sd=6.5)
    assert (over.book, over.line, over.price) == ("draftkings", 24.5, -105)
    under = best_quote(q, "u", projection=22.0, sd=6.5)
    assert (under.book, under.line, under.price) == ("fanduel", 24.5, -105)


def test_best_price_books_disagree_on_line_chosen_per_side():
    # Fair medians 24.5, 25.5, 24.5 -> consensus 24.5.
    q = [
        Quote("fanduel", 24.5, -110, -110),
        Quote("draftkings", 25.5, -110, -110),
        Quote("betmgm", 24.5, -110, -110),
    ]
    over = best_quote(q, "o", sd=6.5)
    # Over 24.5: fair 0.5, EV 0.5 * 1.909 - 1 = -0.045; over 25.5: fair 0.439, EV -0.162.
    assert (over.book, over.line) == (
        "fanduel",
        24.5,
    )  # FanDuel wins the tie with BetMGM
    assert over.ev == approx(0.5 * (1 + 100 / 110) - 1)
    under = best_quote(q, "u", sd=6.5)
    # Under 25.5: fair = Phi(1/6.5) = 0.5611, EV = 0.5611 * 1.909 - 1 = +0.071.
    assert (under.book, under.line, under.price) == ("draftkings", 25.5, -110)
    assert under.fair_prob == approx(0.5611, abs=1e-3)
    assert under.ev == approx(0.0712, abs=1e-3)


def test_soft_outlier_line_beats_price():
    q = [
        Quote("fanduel", 25.5, -110, -110),
        Quote("draftkings", 25.5, -105, -115),
        Quote("betmgm", 25.5, -110, -110),
        Quote("fanatics", 23.5, -125, -105),
    ]
    over = best_quote(q, "o", sd=6.5)
    # Consensus ~25.5; over 23.5 is ~0.62 fair, worth more than -105 at 25.5.
    assert (over.book, over.line, over.price) == ("fanatics", 23.5, -125)
    # But a price only ever travels with its own line.
    assert all((b.line, b.price) in {(x.line, x.over_price) for x in q} for b in [over])


def test_projection_side_and_reference_books():
    q = [
        Quote("fanduel", 24.5, -110, -110),
        Quote("draftkings", 23.5, -110, +120),  # projection 24 is OVER 23.5
        Quote("pinnacle", 24.5, -110, +150),  # reference only
    ]
    under = best_quote(q, "u", projection=24.0, sd=6.5)
    assert (under.book, under.line, under.price) == ("fanduel", 24.5, -110)
    assert best_quote([Quote("pinnacle", 24.5, -110, -110)], "o") is None


def test_best_without_two_way_quotes_prefers_line_then_price():
    q = [Quote("a", 24.5, -110, None), Quote("b", 23.5, -130, None)]
    assert best_quote(q, "o").book == "b"


def test_clv_sign_conventions():
    # Took over 24.5; it closed 25.5 -> +1 point for the over, -1 for an under.
    assert line_clv("o", 24.5, 25.5) == 1.0
    assert line_clv("u", 24.5, 25.5) == -1.0
    # Same line, close -110/-110: fair 0.5 vs paid 0.5238 -> -0.0238.
    close_same = [Quote("fanduel", 24.5, -110, -110)]
    assert prob_clv("o", 24.5, -110, close_same, sd=6.5) == approx(0.5 - 110 / 210)
    # Took over 24.5 at -110; the close moved to 25.5 -110/-110 -> fair P(over 24.5) 0.5611.
    close_up = [Quote("fanduel", 25.5, -110, -110)]
    assert prob_clv("o", 24.5, -110, close_up, sd=6.5) == approx(
        0.5611 - 0.5238, abs=1e-3
    )
    assert prob_clv("u", 24.5, -110, close_up, sd=6.5) == approx(
        0.4389 - 0.5238, abs=1e-3
    )
    # Took +120 on a line that closed -110/-110: 0.5 - 0.4545 = +0.045.
    assert prob_clv("o", 24.5, +120, close_same, sd=6.5) == approx(0.5 - 100 / 220)
    assert prob_clv("o", 24.5, -110, [Quote("fanduel", 24.5, -110, None)]) is None


def test_median_price_across_even():
    assert prob_to_american(110 / 210) == -110
    assert prob_to_american(0.4) == 150
    # -110 and +100 straddle even money: the median is about -105, not -5.
    assert median_price([-110, 100]) == -105
    assert median_price([-120, -130, -140]) == -130
    assert median_price([]) is None
