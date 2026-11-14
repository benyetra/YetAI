"""Honest walk-forward evaluation of the residual model.

Every scored row is predicted by a model fitted only on rows dated strictly before the
refit day that produced it. Metrics are computed on realised ``resid`` (actual - line).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.auto_pick.parlay_utils import american_to_decimal
from app.services.etl.nba.residual import model as _model
from app.services.etl.nba.residual.dataset import FEATURE_FAMILIES
from app.services.etl.nfl.anytime_td_market_anchor import american_to_implied_prob

fit = _model.fit  # module-level so tests can instrument it
BREAKEVEN_110 = 110 / 210
BUCKETS = [(0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, np.inf)]
THRESHOLDS = [0.0, 0.25, 0.5, 0.75, 1.0]
Z = 1.96


def wilson(hits: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p, z2 = hits / n, Z * Z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z * np.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return float(centre - half), float(centre + half)


# ---------------------------------------------------------------- walk-forward


def walk_forward(
    df: pd.DataFrame,
    features,
    kind="ridge_cv",
    *,
    refit_days=7,
    min_train_rows=300,
    seed=0,
) -> pd.DataFrame:
    """Expanding-window weekly refit. Returns scored rows with pred_resid, p_over,
    fit_date, train_base, alpha. ``seed`` is unused: model seeds are fixed in model.py.
    """
    df = df.sort_values("date").reset_index(drop=True)
    dates = df["date"]
    uniq = np.sort(dates.unique())
    first = next((d for d in uniq if (dates < d).sum() >= min_train_rows), None)
    if first is None:
        return df.iloc[0:0].assign(
            pred_resid=np.nan,
            p_over=np.nan,
            fit_date=pd.NaT,
            train_base=np.nan,
            alpha=np.nan,
        )
    first = pd.Timestamp(first)
    last = dates.max()
    refits = pd.date_range(first, last, freq=f"{refit_days}D")
    parts = []
    for i, r in enumerate(refits):
        nxt = refits[i + 1] if i + 1 < len(refits) else last + pd.Timedelta(days=1)
        mdl = fit(df[dates < r], features, kind)
        seg = df[(dates >= r) & (dates < nxt)].copy()
        if seg.empty:
            continue
        seg["pred_resid"], seg["p_over"] = mdl.predict(seg)
        seg["fit_date"] = r
        seg["alpha"] = np.nan if mdl.alpha is None else mdl.alpha
        seg["train_base"] = df.loc[dates < r, "over"].mean()
        parts.append(seg)
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- metrics


def _ols(x: np.ndarray, y: np.ndarray) -> dict:
    n = len(x)
    if n < 3 or np.ptp(x) == 0:
        return dict(slope=np.nan, intercept=np.nan, slope_se=np.nan, corr=np.nan)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    slope = ((x - xm) * (y - ym)).sum() / sxx
    icpt = ym - slope * xm
    resid = y - (icpt + slope * x)
    se = np.sqrt((resid**2).sum() / (n - 2) / sxx)
    corr = float(np.corrcoef(x, y)[0, 1])
    return dict(
        slope=float(slope), intercept=float(icpt), slope_se=float(se), corr=corr
    )


def _price_for_side(rows: pd.DataFrame, side: np.ndarray) -> np.ndarray:
    """Stored price for the called side (+1 over / -1 under); NaN if not quoted."""
    price = np.where(side > 0, rows["over_price"], rows["under_price"]).astype(float)
    ps = rows["price_side"].fillna("")
    ok = ps.isin(["both", "over"]) & (side > 0) | ps.isin(["both", "under"]) & (
        side < 0
    )
    return np.where(ok, price, np.nan)


def _calls(rows: pd.DataFrame) -> dict:
    """Hit/ROI summary for rows already restricted to the calls being summarised."""
    side = np.sign(rows["pred_resid"].to_numpy())
    res = rows["resid"].to_numpy()
    np_ = res != 0
    hit = (res * side > 0) & np_
    n, h = int(np_.sum()), int(hit[np_].sum())
    lo, hi = wilson(h, n)
    out = dict(
        n=n,
        hits=h,
        hit_rate=h / n if n else np.nan,
        wilson_lo=lo,
        wilson_hi=hi,
        roi_units_110=(h * 100 / 110 - (n - h)),
        n_over=int((side[np_] > 0).sum()),
        n_under=int((side[np_] < 0).sum()),
    )
    price = _price_for_side(rows, side)
    pm = np_ & ~np.isnan(price)
    sp = dict(n=int(pm.sum()))
    if pm.any():
        pr = price[pm]
        wins = hit[pm]
        pay = np.array([american_to_decimal(int(p)) - 1 for p in pr])
        # Median in probability space: the median of American odds that straddle
        # +-100 is meaningless (+100 and -118 give -9).
        ip = np.array([american_to_implied_prob(float(x)) for x in pr])
        med = float(pr[np.argsort(ip)[len(ip) // 2]])
        sp.update(
            hits=int(wins.sum()),
            hit_rate=float(wins.mean()),
            roi_units=float((pay[wins]).sum() - (~wins).sum()),
            median_price=med,
            breakeven=float(np.median(ip)),
        )
    out["stored_price"] = sp
    return out


def _baselines(rows: pd.DataFrame, train_base_rate: float) -> dict:
    res = rows["resid"].to_numpy()
    np_ = res != 0
    n = int(np_.sum())
    under = float((res[np_] < 0).mean()) if n else np.nan
    base_over = train_base_rate > 0.5
    base = float((res[np_] > 0).mean() if base_over else under) if n else np.nan
    return dict(
        n=n,
        always_under=under,
        always_train_base_side=base,
        base_side="over" if base_over else "under",
    )


def _calibration(rows: pd.DataFrame, train_base_rate: float) -> dict:
    r = rows[rows["over"].notna()]
    p, y = r["p_over"].to_numpy(), r["over"].to_numpy()
    if not len(r):
        return dict(bins=[], mean_abs_gap=np.nan)
    b = np.minimum((p / 0.05).astype(int), 19)
    bins = []
    for k in np.unique(b):
        m = b == k
        bins.append(
            dict(
                lo=round(k * 0.05, 2),
                n=int(m.sum()),
                mean_pred=float(p[m].mean()),
                observed=float(y[m].mean()),
            )
        )
    gap = sum(x["n"] * abs(x["mean_pred"] - x["observed"]) for x in bins) / len(r)
    return dict(
        bins=bins,
        mean_abs_gap=float(gap),
        brier=float(((p - y) ** 2).mean()),
        brier_const_train_base=float(((train_base_rate - y) ** 2).mean()),
        brier_half=float(((0.5 - y) ** 2).mean()),
    )


def _sample_size(p: float, b: float) -> float | None:
    if not (p > b):
        return None
    return float(Z * Z * p * (1 - p) / (p - b) ** 2)


def metrics(scored: pd.DataFrame, *, train_base_rate: float) -> dict:
    s = scored
    out = dict(n=int(len(s)))
    if not len(s):
        return out
    x, y = s["pred_resid"].to_numpy(), s["resid"].to_numpy()
    out.update(_ols(x, y))
    out["mae_line"] = float(np.abs(y).mean())
    out["mae_model"] = float(np.abs(y - x).mean())
    out["mae_delta"] = out["mae_model"] - out["mae_line"]
    mag = s["pred_resid"].abs()
    out["buckets"] = [
        dict(
            lo=lo,
            hi=None if np.isinf(hi) else hi,
            **_calls(s[(mag >= lo) & (mag < hi)]),
        )
        for lo, hi in BUCKETS
    ]
    out["cumulative"] = [
        dict(
            threshold=t,
            **_calls(s[mag >= t]),
            baselines=_baselines(s[mag >= t], train_base_rate),
        )
        for t in THRESHOLDS
    ]
    out["baselines_all"] = _baselines(s, train_base_rate)
    out["calibration"] = _calibration(s, train_base_rate)
    weeks = max((s["date"].max() - s["date"].min()).days / 7, 1.0)
    ss = {}
    for c in out["cumulative"]:
        if c["threshold"] not in (0.5, 1.0) or not c["n"]:
            continue
        brk = [BREAKEVEN_110]
        sp = c["stored_price"]
        if sp.get("breakeven") is not None:
            brk.append(sp["breakeven"])
        need = [_sample_size(c["hit_rate"], b) for b in brk]
        per_week = c["n"] / weeks
        ss[str(c["threshold"])] = dict(
            hit_rate=c["hit_rate"],
            calls_per_week=per_week,
            breakevens=brk,
            n_needed=need,
            weeks_needed=[None if n is None else n / per_week for n in need],
        )
    out["sample_size"] = ss
    out["benchmark_proj"] = benchmark(s)
    return out


def benchmark(scored: pd.DataFrame) -> dict:
    """The stored projection (what is published today) on the same scored rows."""
    r = scored[scored["proj_edge"].notna()]
    if not len(r):
        return dict(n=0)
    out = dict(n=int(len(r)), **_ols(r["proj_edge"].to_numpy(), r["resid"].to_numpy()))
    side = np.sign(r["proj_edge"].to_numpy())
    res = r["resid"].to_numpy()
    m = (res != 0) & (side != 0)
    h = int(((res * side > 0) & m).sum())
    out.update(calls=int(m.sum()), hits=h, hit_rate=h / m.sum() if m.any() else np.nan)
    return out


# ---------------------------------------------------------------- ablation / placebo


def _summary(scored: pd.DataFrame) -> dict:
    if not len(scored):
        return dict(n=0)
    m = metrics(scored, train_base_rate=scored["train_base"].mean())
    c = next(c for c in m["cumulative"] if c["threshold"] == 0.5)
    return dict(
        n=m["n"],
        slope=m["slope"],
        slope_se=m["slope_se"],
        corr=m["corr"],
        mae_delta=m["mae_delta"],
        hit_050=c["hit_rate"],
        n_050=c["n"],
    )


def ablation(df: pd.DataFrame, families, kind="ridge_cv", **wf) -> list[dict]:
    """Walk-forward with each family dropped, and with only that family (+ line_)."""
    out = []
    for fam in families:
        drop = [c for f in families if f != fam for c in FEATURE_FAMILIES[f]]
        only = list(dict.fromkeys(FEATURE_FAMILIES["line_"] + FEATURE_FAMILIES[fam]))
        for mode, feats in (("drop", drop), ("only", only)):
            if feats:
                out.append(
                    dict(
                        family=fam,
                        mode=mode,
                        **_summary(walk_forward(df, feats, kind, **wf)),
                    )
                )
    return out


def placebo(
    df: pd.DataFrame, features, kind="ridge_cv", seeds=range(5), **wf
) -> list[dict]:
    """Shuffle resid and over together within date, rerun the identical walk-forward."""
    out = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        d = df.copy()
        cols = [d.columns.get_loc("resid"), d.columns.get_loc("over")]
        for _, idx in d.groupby("date").indices.items():
            # cyclic shift of a random order: a permutation where no row keeps its own
            order = rng.permutation(idx)
            d.iloc[np.roll(order, 1), cols] = d.iloc[order, cols].to_numpy()
        out.append(
            dict(seed=int(seed), **_summary(walk_forward(d, features, kind, **wf)))
        )
    return out


def verdict(m: dict) -> str:
    """Pre-declared rule on the adopted model's metrics (never tuned on results).

    confirmed: slope CI above 0, MAE below the line's, and the Wilson lower bound of the
    >=0.5 calls above the -110 breakeven. suggestive: slope > 0 and the >=0.5 hit rate
    above the -110 breakeven and above both baselines, but not confirmed. else none."""
    c = next(c for c in m["cumulative"] if c["threshold"] == 0.5)
    if not c["n"] or not m["n"]:
        return "none"
    if (
        m["slope"] - Z * m["slope_se"] > 0
        and m["mae_delta"] < 0
        and c["wilson_lo"] > BREAKEVEN_110
    ):
        return "edge confirmed"
    bl = c["baselines"]
    if (
        m["slope"] > 0
        and c["hit_rate"] > BREAKEVEN_110
        and c["hit_rate"] > max(bl["always_under"], bl["always_train_base_side"])
    ):
        return "suggestive but unproven"
    return "none"
