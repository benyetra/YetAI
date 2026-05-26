#!/usr/bin/env python3
"""Smoke PA-level sim pilot (no deploy; requires DB profiles optional)."""

from __future__ import annotations

import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    from app.core.database import SessionLocal
    from app.services.etl.mlb.profiles.pa_sim_pilot import simulate_game_pa_pilot
    from app.services.etl.mlb.profiles.profile_store import ProfileStore

    if SessionLocal is None:
        logger.warning("DATABASE_URL unset — using mock lineups only")
        return 0

    # Minimal synthetic pilot when DB empty
    db = SessionLocal()
    try:
        store = ProfileStore(db)
        result = simulate_game_pa_pilot(
            store,
            home_lineup=list(range(600000, 600009)),
            away_lineup=list(range(600100, 600109)),
            home_pitcher_id=500001,
            away_pitcher_id=500002,
            as_of_date=date.today(),
            n_sims=1000,
        )
        logger.info(
            "pilot home_mu=%.2f away_mu=%.2f wp=%.3f runtime=%.2fs",
            result.home_runs_mean,
            result.away_runs_mean,
            result.home_win_prob,
            result.runtime_sec,
        )
        if result.runtime_sec > 60:
            logger.error("runtime exceeds 60s target at 1k sims")
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
