import numpy as np
import pytest

from app.services.fair_price import consensus


def test_blend_hand():
    # logit .6 = .4054651, logit .5 = 0 -> mean .2027326 -> .5505103; 3:1 -> .3040988 -> .5754442
    assert consensus.blend({"a": 0.6, "b": 0.5}, None) == pytest.approx(
        0.5505103, abs=1e-6
    )
    assert consensus.blend({"a": 0.6, "b": 0.5}, {"a": 3, "b": 1}) == pytest.approx(
        0.5754442, abs=1e-6
    )
    assert consensus.blend({"a": 0.6, "b": 0.5}, {"a": 3}) == pytest.approx(
        0.5754442, abs=1e-6
    )
    with pytest.raises(ValueError):
        consensus.blend({}, None)


def _rows(n, noise_b, seed=0, extra=None):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        p = rng.uniform(0.2, 0.8)
        y = int(rng.random() < p)
        lg = np.log(p / (1 - p))
        q = lambda s: float(1 / (1 + np.exp(-(lg + rng.normal(0, s)))))  # noqa: E731
        rows.append(({"a": q(0.02) if noise_b else q(0.3), "b": q(noise_b or 0.3)}, y))
    return rows


def test_informative_book_wins():
    rows = _rows(3000, 1.0)
    out = consensus.fit_weights(rows)
    assert set(out["fitted"]) == {"a", "b"}
    assert out["weights"]["a"] > 2 * out["weights"]["b"]
    assert np.sqrt(out["weights"]["a"] * out["weights"]["b"]) == pytest.approx(1.0)


def test_equal_books():
    out = consensus.fit_weights(_rows(3000, None, seed=1))
    w = out["weights"]
    assert abs(w["a"] / w["b"] - 1) < 0.1


def test_min_n():
    rows = _rows(3000, 1.0)
    rng = np.random.default_rng(5)
    rows += [({"a": 0.5, "c": 0.6}, int(rng.random() < 0.5)) for _ in range(200)]
    out = consensus.fit_weights(rows)
    assert out["weights"]["c"] == 1.0 and "c" not in out["fitted"]
    assert out["n"]["c"] == 200
    only = consensus.fit_weights(rows[:100])
    assert only["fitted"] == [] and set(only["weights"].values()) == {1.0}
