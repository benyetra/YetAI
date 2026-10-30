#!/usr/bin/env python
"""Smoke test MLB Monte Carlo without DB or network.

  cd backend && PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_monte_carlo.py
"""

from __future__ import annotations

import sys

from app.services.etl.mlb.monte_carlo import (
    DEFAULT_N_SIMS,
    TeamRunRates,
    monte_carlo_enabled,
    simulate_game,
)


def main() -> int:
    if not monte_carlo_enabled():
        print("MLB_MC_ENABLED is off — set MLB_MC_ENABLED=1 to run smoke.")
        return 1

    rates = TeamRunRates(home_mu=4.6, away_mu=4.1)
    sim = simulate_game(rates, n_sims=min(DEFAULT_N_SIMS, 5000), seed=42)
    print(f"n_sims={sim.n_sims}")
    print(f"home_win_prob={sim.home_win_prob:.3f}")
    print(
        f"total_mean={sim.projected_total_mean:.2f} std={sim.projected_total_std:.2f}"
    )
    print(f"total p50={sim.percentiles_total.get('p50')}")
    print(
        f"margin p10/p90={sim.percentiles_margin.get('p10')} / {sim.percentiles_margin.get('p90')}"
    )
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
