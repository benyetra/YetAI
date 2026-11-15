import pytest

from app.services.fair_price import lines


def test_hand_values():
    assert lines.p_over(6.5, 6, 1.3) == pytest.approx(0.3927746, abs=1e-6)
    assert lines.p_over(7.5, 6, 1.3) == pytest.approx(0.2721399, abs=1e-6)
    assert lines.p_over(5.5, 6, 1.3) == pytest.approx(0.5335151, abs=1e-6)
    assert lines.p_over(6, 6, 1.3) == pytest.approx(0.4571082, abs=1e-6)
    assert lines.p_over(6.5, 6, 1.0) == pytest.approx(0.3936972, abs=1e-6)


def test_mean_for_round_trip():
    assert lines.mean_for(6.5, 0.3927746, 1.3) == pytest.approx(6, abs=1e-4)
    assert lines.mean_for(6.5, 0.01, 1.3) is None
    assert lines.mean_for(6.5, 0.99, 1.3) is None


def test_convert(monkeypatch):
    monkeypatch.setitem(lines.PHI, "t", 1.3)
    monkeypatch.setitem(lines.MAX_SHIFT, "t", 2.0)
    assert lines.convert(0.3927746, 6.5, 7.5, "t") == pytest.approx(0.2721399, abs=1e-6)
    assert lines.convert(0.4, 6.5, 6.5, "t") == 0.4
    assert lines.convert(0.4, 6.5, 9.5, "t") is None
    assert lines.convert(0.4, 6.5, 7.5, "nope") is None
