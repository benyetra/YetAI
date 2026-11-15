"""Consensus across books: logarithmic pool and its fitted weights."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np
from scipy.optimize import minimize


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def blend(
    probs: dict[str, float],
    weights: dict[str, float] | None,
    default_weight: float = 1.0,
) -> float:
    """Log pool: logit p* = sum_b w_b logit p_b / sum_b w_b over the books in probs
    (a book missing from weights gets default_weight). Empty input -> ValueError."""
    if not probs:
        raise ValueError("blend needs at least one book")
    w = weights or {}
    ws = {b: w.get(b, default_weight) for b in probs}
    z = sum(ws[b] * _logit(p) for b, p in probs.items()) / sum(ws.values())
    return 1 / (1 + math.exp(-z))


def fit_weights(
    rows: list[tuple[dict[str, float], int]], *, min_n: int = 300, l2: float = 1.0
) -> dict:
    """Fit w_b = exp(theta_b) minimising mean log loss of blend(probs, w) plus
    (l2 / N) * sum theta_b^2 (shrinks toward equal weights), L-BFGS-B. Books in fewer than
    min_n rows keep weight 1.0. Weights rescaled to geometric mean 1 over fitted books;
    fewer than 2 fitted books -> all 1.0."""
    n = Counter(b for probs, _ in rows for b in probs)
    books = sorted(b for b, c in n.items() if c >= min_n)
    out_w = {b: 1.0 for b in n}
    res_ll = float("nan")
    if len(books) >= 2 and rows:
        idx = {b: i for i, b in enumerate(books)}
        N = len(rows)
        lg = np.zeros((N, len(books)))  # logits of fitted books (0 where absent)
        has = np.zeros((N, len(books)))
        fixed = np.zeros(N)  # sum of logits of unfitted books (theta = 0, w = 1)
        fixed_w = np.zeros(N)
        y = np.array([o for _, o in rows], dtype=float)
        for r, (probs, _) in enumerate(rows):
            for b, p in probs.items():
                if b in idx:
                    lg[r, idx[b]] = _logit(p)
                    has[r, idx[b]] = 1.0
                else:
                    fixed[r] += _logit(p)
                    fixed_w[r] += 1.0

        def loss(theta: np.ndarray) -> float:
            w = np.exp(theta)
            den = has @ w + fixed_w
            ok = den > 0
            z = np.zeros(N)
            z[ok] = ((lg * has) @ w + fixed)[ok] / den[ok]
            ll = np.logaddexp(0, z) - y * z  # -log-likelihood of Bernoulli(sigmoid z)
            return float(ll.mean() + l2 / N * np.sum(theta**2))

        theta = minimize(loss, np.zeros(len(books)), method="L-BFGS-B").x
        theta = theta - theta.mean()  # geometric mean 1 over fitted books
        for b in books:
            out_w[b] = float(math.exp(theta[idx[b]]))
        res_ll = loss(theta) - l2 / N * float(np.sum(theta**2))
    else:
        books = []
    return {"weights": out_w, "n": dict(n), "fitted": books, "log_loss": res_ll}
