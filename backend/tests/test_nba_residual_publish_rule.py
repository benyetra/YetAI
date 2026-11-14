import math
import pathlib

import pytest

from app.services.etl.nba.residual.publish_rule import decide

# d(-110)=1.90909, d(-125)=1.8, d(+100)=2.0


def test_over_capped_stake():
    # EV = 0.6*1.90909-1 = 0.14545; f* = (0.90909*0.6-0.4)/0.90909 = 0.16;
    # quarter Kelly 0.04 -> capped to 0.02
    r = decide(0.60, -110, -110, p_se=0, calibration_error=0)
    assert r.side == "over" and r.reason == "bet"
    assert r.ev == pytest.approx(0.14545, abs=1e-4)
    assert r.stake == pytest.approx(0.02)


def test_uncapped_stake():
    r = decide(0.60, -110, -110, p_se=0, calibration_error=0, max_stake=1)
    assert r.stake == pytest.approx(0.04)


def test_negative_ev_no_bet():
    # 0.55*1.8-1 = -0.01
    r = decide(0.55, -125, None, p_se=0, calibration_error=0)
    assert r.side is None and r.reason == "below_threshold"


def test_conservative_margin():
    # p_c = 0.58-(0.02+0.01) = 0.55 -> EV_c = -0.01 -> no bet
    r = decide(0.58, -125, None, p_se=0.02, calibration_error=0.01)
    assert r.side is None and r.reason == "below_threshold"
    # no margin: 0.58*1.8-1 = 0.044 -> bet
    r = decide(0.58, -125, None, p_se=0, calibration_error=0)
    assert r.side == "over" and r.ev_conservative == pytest.approx(0.044)


def test_under_side():
    # p_under 0.65 at +100 (d 2.0): EV 0.30
    r = decide(0.35, -110, 100, p_se=0, calibration_error=0)
    assert r.side == "under" and r.ev == pytest.approx(0.30)


def test_missing_price():
    r = decide(0.60, None, -110, p_se=0, calibration_error=0)  # under p=.4: EV<0
    assert r.side is None and r.reason == "below_threshold"
    r = decide(0.35, None, 100, p_se=0, calibration_error=0)
    assert r.side == "under"
    r = decide(0.60, None, None, p_se=0, calibration_error=0)
    assert r.reason == "no_price"


@pytest.mark.parametrize(
    "p,o,u",
    [
        (1.2, -110, -110),
        (-0.1, -110, -110),
        (0.5, 0, -110),
        (0.5, -50, -110),
        (0.5, 99, -110),
        (float("nan"), -110, -110),
        (0.5, float("nan"), -110),
    ],
)
def test_invalid(p, o, u):
    assert decide(p, o, u, p_se=0, calibration_error=0).reason == "invalid_input"


def test_even_money_boundary():
    # +100 and -100 are valid
    assert decide(0.6, 100, -100, p_se=0, calibration_error=0).reason == "bet"


def test_not_imported_by_auto_pick():
    root = pathlib.Path(__file__).resolve().parents[1] / "app/services/auto_pick"
    for f in root.rglob("*.py"):
        assert "publish_rule" not in f.read_text(), f
