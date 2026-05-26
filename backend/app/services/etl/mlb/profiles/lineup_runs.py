"""Lineup-weighted run expectations for Monte Carlo (Phase 5)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.etl.mlb.monte_carlo import TeamRunRates
from app.services.etl.mlb.profiles.constants import mlb_profiles_enabled
from app.services.etl.mlb.profiles.matchup_contact import contact_matchup_score
from app.services.etl.mlb.profiles.matchup_k import compute_lineup_k_matchup
from app.services.etl.mlb.profiles.profile_store import ProfileStore

# Run-rate nudge per unit of contact edge / K matchup factor (tuned conservatively).
CONTACT_RUN_SCALE = 0.35
K_MATCHUP_RUN_SCALE = -0.12


def _lineup_offense_adjustment(
    store: ProfileStore,
    lineup: list[int],
    pitcher_id: int,
    pitcher_hand: str,
    as_of_date: date,
    window: str = "season",
) -> tuple[float, list[str]]:
    """Signed adjustment to team mu from profile matchups."""
    if not lineup:
        return 0.0, []

    k_result = compute_lineup_k_matchup(
        store, pitcher_id, lineup, pitcher_hand, as_of_date, window
    )
    sources = [k_result.source]
    contact_sum = 0.0
    n_contact = 0
    for bid in lineup:
        delta, _ = contact_matchup_score(
            store, bid, pitcher_id, pitcher_hand, as_of_date, window
        )
        contact_sum += delta
        n_contact += 1

    contact_avg = contact_sum / n_contact if n_contact else 0.0
    adj = CONTACT_RUN_SCALE * contact_avg + K_MATCHUP_RUN_SCALE * k_result.factor
    return round(adj, 4), sources


def expected_runs_from_lineup(
    store: ProfileStore,
    home_lineup: list[int],
    away_lineup: list[int],
    home_pitcher_id: int,
    away_pitcher_id: int,
    as_of_date: date,
    base_rates: TeamRunRates,
    *,
    home_pitcher_hand: str = "R",
    away_pitcher_hand: str = "R",
    window: str = "season",
) -> tuple[TeamRunRates, dict[str, Any]]:
    """
    Adjust baseline team run rates using profile tensors for both lineups.
    """
    home_adj, home_sources = _lineup_offense_adjustment(
        store, home_lineup, away_pitcher_id, away_pitcher_hand, as_of_date, window
    )
    away_adj, away_sources = _lineup_offense_adjustment(
        store, away_lineup, home_pitcher_id, home_pitcher_hand, as_of_date, window
    )

    home_mu = max(0.5, base_rates.home_mu + home_adj)
    away_mu = max(0.5, base_rates.away_mu + away_adj)

    all_sources = home_sources + away_sources
    archetype_pct = (
        sum(1 for s in all_sources if s == "archetype") / len(all_sources)
        if all_sources
        else 0.0
    )
    observed_pct = (
        sum(1 for s in all_sources if s == "observed") / len(all_sources)
        if all_sources
        else 0.0
    )

    meta = {
        "lineup_weighted": True,
        "home_lineup_size": len(home_lineup),
        "away_lineup_size": len(away_lineup),
        "home_run_adj": home_adj,
        "away_run_adj": away_adj,
        "avg_reliability_hint": round(observed_pct, 3),
        "archetype_pct": round(archetype_pct, 3),
        "matchup_sources": list(set(all_sources)),
    }
    return TeamRunRates(home_mu=round(home_mu, 3), away_mu=round(away_mu, 3)), meta


def maybe_adjust_rates_from_lineups(
    features: dict[str, Any],
    base_rates: TeamRunRates,
    as_of_date: date,
    db=None,
) -> tuple[TeamRunRates, dict[str, Any] | None]:
    """Apply lineup profile adjustment when enabled and lineups are present."""
    if not mlb_profiles_enabled():
        return base_rates, None

    home_lineup = features.get("home_lineup") or features.get("home_lineup_ids")
    away_lineup = features.get("away_lineup") or features.get("away_lineup_ids")
    home_pid = features.get("home_pitcher_id")
    away_pid = features.get("away_pitcher_id")

    if not (home_lineup and away_lineup and home_pid and away_pid):
        return base_rates, None

    try:
        from app.core.database import SessionLocal

        session = db
        own = False
        if session is None and SessionLocal is not None:
            session = SessionLocal()
            own = True
        if session is None:
            return base_rates, None

        store = ProfileStore(session)
        rates, meta = expected_runs_from_lineup(
            store,
            [int(x) for x in home_lineup],
            [int(x) for x in away_lineup],
            int(home_pid),
            int(away_pid),
            as_of_date,
            base_rates,
            home_pitcher_hand=str(features.get("home_pitcher_hand", "R")),
            away_pitcher_hand=str(features.get("away_pitcher_hand", "R")),
        )
        if own:
            session.close()
        return rates, meta
    except Exception:
        return base_rates, None
