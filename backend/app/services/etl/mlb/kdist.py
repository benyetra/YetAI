# --- scripts/mlb/kdist.py ---
import math

def negbin_prob_over(mu: float, var: float, threshold: float) -> float:
    """
    Negative Binomial tail P(K > threshold) with mean mu and variance var (var >= mu).
    Using r,p parameterization: r = mu^2 / (var - mu), p = r/(r+mu)
    Uses a simple summation up to threshold (ok for small thresholds like 3-10).
    """
    if mu <= 0:
        return 0.0
    var = max(var, mu * 1.25)  # ensure over-dispersion
    if var <= mu:
        # Poisson fallback
        return 1.0 - poisson_cdf(threshold, mu)

    r = (mu * mu) / (var - mu)
    p = r / (r + mu)
    # P(X <= t) = sum_{k=0..t} C(k+r-1,k) * (1-p)^k * p^r
    cdf = 0.0
    t = int(math.floor(threshold))
    for k in range(0, t + 1):
        coeff = nCr(k + r - 1, k)
        cdf += coeff * ((1 - p) ** k) * (p ** r)
    return max(0.0, min(1.0, 1.0 - cdf))

def nCr(n, r):
    # works for real n (via gamma)
    from math import gamma
    return gamma(n + 1) / (gamma(r + 1) * gamma(n - r + 1))

def poisson_cdf(t, lam):
    # quick Poisson cdf via summation
    from math import exp
    t = int(math.floor(t))
    s = 0.0
    term = math.exp(-lam)
    s += term
    for k in range(1, t + 1):
        term *= lam / k
        s += term
    return s
