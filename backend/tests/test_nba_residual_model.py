import pickle

import numpy as np
import pandas as pd

from app.services.etl.nba.residual import evaluate as ev
from app.services.etl.nba.residual import model as md

FEATS = ["f1", "f2"]


def _synth(signal=True, n_days=120, per_day=6, seed=0):
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    d = pd.Timestamp("2026-01-01") + pd.to_timedelta(
        np.repeat(np.arange(n_days), per_day), "D"
    )
    f1, f2 = rng.normal(size=n), rng.normal(size=n)
    line = rng.integers(4, 12, n) + 0.5
    true = 1.2 * f1 if signal else np.zeros(n)
    actual = line + true + rng.normal(0, 2, n)
    df = pd.DataFrame(
        dict(date=d, player_id=np.arange(n), line=line, f1=f1, f2=f2, actual=actual)
    )
    df["resid"] = df["actual"] - df["line"]
    df["over"] = (df["resid"] > 0).astype(float)
    df["proj_edge"] = df["f1"]
    for c in ("over_price", "under_price"):
        df[c] = np.nan
    df["price_side"] = None
    return df


def test_walk_forward_never_fits_on_scored_dates(monkeypatch):
    df = _synth()
    seen = []
    real = md.fit

    def spy(train, features, kind="ridge", **kw):
        seen.append((train["date"].max(), train["date"].max()))
        return real(train, features, kind, **kw)

    monkeypatch.setattr(ev, "fit", spy)
    scored = ev.walk_forward(df, FEATS, "ridge_cv", min_train_rows=100)
    fits = scored.groupby("fit_date").size().index
    assert len(seen) == len(fits) > 3
    for (max_train, _), fit_date in zip(seen, fits):
        assert max_train < fit_date
    assert (scored["fit_date"] <= scored["date"]).all()
    assert (scored["date"] >= scored["fit_date"].min()).all()


def test_signal_has_positive_slope_and_beats_line():
    sc = ev.walk_forward(_synth(True), FEATS, "ridge", min_train_rows=100)
    m = ev.metrics(sc, train_base_rate=0.5)
    assert m["slope"] > 0.5 and m["mae_delta"] < 0
    assert m["benchmark_proj"]["slope"] > 0


def test_noise_slope_ci_covers_zero_and_placebo_has_no_skill():
    df = _synth(False)
    sc = ev.walk_forward(df, FEATS, "ridge", min_train_rows=100)
    m = ev.metrics(sc, train_base_rate=0.5)
    assert abs(m["slope"]) < 2 * m["slope_se"]
    sig = _synth(True)
    for p in ev.placebo(sig, FEATS, "ridge", seeds=(0, 1, 2), min_train_rows=100):
        assert abs(p["slope"]) < 3 * p["slope_se"] and p["mae_delta"] > -0.1


def test_model_pickles_with_identical_predictions():
    df = _synth()
    for kind in ("ridge_cv", "ridge", "gbm"):
        m = md.fit(df, FEATS, kind, stat="rebounds")
        m2 = pickle.loads(pickle.dumps(m))
        a, b = m.predict(df), m2.predict(df)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
        end = df["date"].max().strftime("%Y%m%d")
        assert m.version == f"resid-rebounds-{kind}-{end}" and m.n_train == len(df)


def test_wilson_and_roi_hand_computed():
    # 6 calls: over wins, over wins, under wins, under loses, over loses, over push
    rows = pd.DataFrame(
        dict(
            date=pd.Timestamp("2026-01-01"),
            pred_resid=[1.0, 1.0, -1.0, -1.0, 1.0, 1.0],
            resid=[2.0, 1.0, -3.0, 1.0, -2.0, 0.0],
            over_price=[-120, np.nan, np.nan, np.nan, 150, np.nan],
            under_price=[np.nan] * 6,
            price_side=["over", None, None, None, "over", None],
            over=[1.0, 1.0, 0.0, 1.0, 0.0, np.nan],
            p_over=0.5,
            proj_edge=0.0,
        )
    )
    c = ev._calls(rows)
    assert (c["n"], c["hits"]) == (5, 3)  # push excluded
    assert abs(c["roi_units_110"] - (3 * 100 / 110 - 2)) < 1e-9
    assert (c["n_over"], c["n_under"]) == (3, 2)
    lo, hi = ev.wilson(3, 5)  # z=1.96, p=.6, n=5
    assert abs(lo - 0.2307) < 1e-3 and abs(hi - 0.8824) < 1e-3
    sp = c["stored_price"]  # over rows with price: win at -120, loss at +150
    assert sp["n"] == 2 and sp["hits"] == 1
    assert abs(sp["roi_units"] - (100 / 120 - 1)) < 1e-9
    assert abs(sp["breakeven"] - american_be(sp["median_price"])) < 1e-12
    assert ev._sample_size(0.6, 0.5238) > 0 and ev._sample_size(0.5, 0.5238) is None


def american_be(p):
    return abs(p) / (abs(p) + 100) if p < 0 else 100 / (p + 100)


def test_ridge_cv_alpha_larger_on_noise_than_signal():
    a_noise = md.fit(_synth(False), FEATS, "ridge_cv").alpha
    a_sig = md.fit(_synth(True), FEATS, "ridge_cv").alpha
    assert a_noise > a_sig and a_noise in md.CV_ALPHAS


def test_oof_platt_never_scores_a_row_with_a_model_that_trained_on_it(monkeypatch):
    df = _synth().assign(f1=lambda d: np.arange(len(d), dtype=float))  # unique ids
    calls, overlaps = [], []
    real = md._fit_est

    class Spy:
        def __init__(self, est, train_ids):
            self.est, self.train_ids = est, train_ids

        def predict(self, x):
            overlaps.append(len(self.train_ids & set(x[:, 0])))
            return self.est.predict(x)

    def spy(kind, x, y):
        calls.append(len(x))
        return Spy(real(kind, x, y), set(x[:, 0]))

    monkeypatch.setattr(md, "_fit_est", spy)
    m = md.fit(df, ["f1"], "ridge")
    assert len(calls) == md.N_SPLITS + 1 and calls[0] == len(df)
    assert all(c < len(df) for c in calls[1:])
    assert overlaps == [0] * md.N_SPLITS  # no in-sample predictions: OOF was used
    assert m.platt != (0.0, 0.0)


def test_invalid_price_is_missing():
    from app.services.etl.nba.residual.dataset import _valid_price

    p = _valid_price(pd.Series([-9, 0, np.nan, -110, 105, 99]))
    assert p.isna().tolist() == [True, True, True, False, False, True]
