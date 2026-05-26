"""Plate-appearance level simulation pilot (Phase 7 — not production MC)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.services.etl.mlb.profiles.constants import LEAGUE_WHIFF_BY_PITCH
from app.services.etl.mlb.profiles.profile_store import ProfileStore

OUTCOMES = ("K", "BB", "BIP", "HR")


@dataclass
class PaSimPilotResult:
    n_sims: int
    home_runs_mean: float
    away_runs_mean: float
    home_win_prob: float
    runtime_sec: float
    outcome_rates: dict[str, float] = field(default_factory=dict)


def _pitch_outcome_probs(batter_profile: dict, pitch_type: str) -> dict[str, float]:
    whiff = float((batter_profile.get("whiff_by_pitch") or {}).get(pitch_type, 0.25))
    barrel = float(
        (batter_profile.get("barrel_rate_by_pitch") or {}).get(pitch_type, 0.08)
    )
    k_p = min(0.45, whiff * 0.85)
    hr_p = min(0.12, barrel * 0.4)
    bb_p = 0.08
    bip_p = max(0.0, 1.0 - k_p - bb_p - hr_p)
    return {"K": k_p, "BB": bb_p, "BIP": bip_p, "HR": hr_p}


def simulate_inning_half(
    rng: np.random.Generator,
    lineup: list[int],
    pitcher_usage: dict[str, float],
    batter_profiles: dict[int, dict],
) -> int:
    runs = 0
    outs = 0
    idx = 0
    while outs < 3 and idx < 50:
        bid = lineup[idx % len(lineup)]
        idx += 1
        bp = batter_profiles.get(bid, {})
        pitches = list(pitcher_usage.keys()) or list(LEAGUE_WHIFF_BY_PITCH.keys())
        weights = [pitcher_usage.get(p, 1.0 / len(pitches)) for p in pitches]
        weights = np.array(weights) / sum(weights)
        pt = str(rng.choice(pitches, p=weights))
        probs = _pitch_outcome_probs(bp, pt)
        labels, pvals = zip(*probs.items())
        outcome = rng.choice(labels, p=pvals)
        if outcome == "K":
            outs += 1
        elif outcome == "BB":
            pass
        elif outcome == "HR":
            runs += 1
            outs += 1
        else:
            if rng.random() < 0.28:
                outs += 1
            elif rng.random() < 0.05:
                runs += 1
    return runs


def simulate_game_pa_pilot(
    store: ProfileStore,
    home_lineup: list[int],
    away_lineup: list[int],
    home_pitcher_id: int,
    away_pitcher_id: int,
    as_of_date: date,
    *,
    home_pitcher_hand: str = "R",
    away_pitcher_hand: str = "R",
    n_sims: int = 10_000,
    seed: int = 42,
) -> PaSimPilotResult:
    """9-inning pilot: usage → pitch type → batter posterior outcome."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)

    hp = store.get_pitcher(home_pitcher_id, as_of_date)
    ap = store.get_pitcher(away_pitcher_id, as_of_date)
    home_usage = (hp.profile or {}).get("usage", {"FF": 1.0}) if hp else {"FF": 1.0}
    away_usage = (ap.profile or {}).get("usage", {"FF": 1.0}) if ap else {"FF": 1.0}

    home_batters: dict[int, dict] = {}
    away_batters: dict[int, dict] = {}
    for bid in home_lineup:
        s = store.get_batter(bid, away_pitcher_hand, as_of_date)
        home_batters[bid] = s.profile if s else {}
    for bid in away_lineup:
        s = store.get_batter(bid, home_pitcher_hand, as_of_date)
        away_batters[bid] = s.profile if s else {}

    home_totals = []
    away_totals = []
    outcome_counts = {o: 0 for o in OUTCOMES}
    n_pitches_est = 0

    for _ in range(n_sims):
        h, a = 0, 0
        for _inn in range(9):
            h += simulate_inning_half(rng, home_lineup, away_usage, home_batters)
            a += simulate_inning_half(rng, away_lineup, home_usage, away_batters)
            n_pitches_est += 30
        home_totals.append(h)
        away_totals.append(a)

    home_arr = np.array(home_totals)
    away_arr = np.array(away_totals)
    runtime = time.perf_counter() - t0

    return PaSimPilotResult(
        n_sims=n_sims,
        home_runs_mean=float(home_arr.mean()),
        away_runs_mean=float(away_arr.mean()),
        home_win_prob=float(np.mean(home_arr > away_arr)),
        runtime_sec=round(runtime, 3),
        outcome_rates={"pitches_est": n_pitches_est / max(n_sims, 1)},
    )
