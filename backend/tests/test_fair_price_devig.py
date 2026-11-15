import pytest

from app.services.fair_price import devig
from app.services.odds_math import american_to_prob


def pis(a, b):
    return [american_to_prob(a), american_to_prob(b)]


@pytest.mark.parametrize("m", list(devig.METHODS))
def test_even_market(m):
    out = devig.METHODS[m](pis(-110, -110))
    assert out == pytest.approx([0.5, 0.5], abs=1e-9)


@pytest.mark.parametrize(
    "a,b,m,want",
    [
        (-150, 130, "multiplicative", 0.5798319),
        (-150, 130, "additive", 0.5826087),
        (-150, 130, "power", 0.5839826),
        (-150, 130, "shin", 0.5826087),
        (-500, 350, "multiplicative", 0.7894737),
        (-500, 350, "additive", 0.8055556),
        (-500, 350, "power", 0.8150126),
    ],
)
def test_hand_values(a, b, m, want):
    out = devig.METHODS[m](pis(a, b))
    assert out[0] == pytest.approx(want, abs=1e-6)
    assert sum(out) == pytest.approx(1, abs=1e-9)


def test_power_exponent():
    assert devig.power_exponent(pis(-150, 130)) == pytest.approx(1.0529699, abs=1e-6)
    assert devig.power_exponent(pis(-500, 350)) == pytest.approx(1.1219285, abs=1e-6)


def test_three_outcome():
    # pi = .5, .3, .3 (S = 1.1): multiplicative = pi / 1.1; shin/power must sum to 1, keep order
    p = [0.5, 0.3, 0.3]
    assert devig.multiplicative(p) == pytest.approx([0.5 / 1.1, 0.3 / 1.1, 0.3 / 1.1])
    for m in (devig.power, devig.shin):
        out = m(p)
        assert sum(out) == pytest.approx(1, abs=1e-9)
        assert out[0] > out[1] == pytest.approx(out[2])
    # power check by hand: k s.t. .5^k + 2 * .3^k = 1 -> k = 1.1 gives .4665+.5319 = .9984 (<1) so k < 1.1
    assert 1.0 < devig.power_exponent(p) < 1.1


def test_additive_fails_on_nonpositive():
    assert devig.additive([0.95, 0.03, 0.2]) is None  # 0.03 - 0.0600 < 0


def test_two_way_and_one_sided():
    assert devig.two_way(-150, 130, "multiplicative") == pytest.approx(
        (0.5798319, 0.4201681), abs=1e-6
    )
    assert devig.two_way(None, 130) is None
    assert devig.two_way(-150, 130, "additive") == pytest.approx(
        (0.5826087, 0.4173913), abs=1e-6
    )
    assert devig.one_sided(-150, 1.0529699) == pytest.approx(0.6**1.0529699, abs=1e-9)
