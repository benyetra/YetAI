"""Kicker FG volume: attempt estimation + distance-mixture make probability."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from app.services.etl.nfl.kicker_weather import weather_make_multiplier

logger = logging.getLogger(__name__)

_NFL_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "nfl"

# Historical distance-band weights (league attempt mix)
_DISTANCE_WEIGHTS: tuple[tuple[float, float], ...] = (
    (25.0, 0.15),
    (35.0, 0.35),
    (45.0, 0.30),
    (55.0, 0.15),
    (65.0, 0.05),
)

_BAND_PRIORS: dict[str, float] = {
    "<30": 0.95,
    "30-39": 0.90,
    "40-49": 0.75,
    "50-59": 0.55,
    "60+": 0.30,
}


def _distance_band(distance: float) -> str:
    if distance < 30:
        return "<30"
    if distance < 40:
        return "30-39"
    if distance < 50:
        return "40-49"
    if distance < 60:
        return "50-59"
    return "60+"


def _load_fg_history() -> pd.DataFrame | None:
    path = _NFL_DATA_DIR / "field_goal_data.csv"
    if not path.is_file():
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:
        logger.info("FG history unavailable: %s", exc)
        return None


def band_make_rates_from_history(
    history: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Empirical make rate by distance band from nflverse CSV."""
    rates = dict(_BAND_PRIORS)
    df = history if history is not None else _load_fg_history()
    if df is None or df.empty or "is_made" not in df.columns:
        return rates
    if "distance_band" in df.columns:
        for band, grp in df.groupby("distance_band"):
            if len(grp) >= 30:
                rates[str(band)] = float(grp["is_made"].mean())
    elif "kick_distance" in df.columns:
        for dist, _ in _DISTANCE_WEIGHTS:
            band = _distance_band(dist)
            lo, hi = dist - 5, dist + 5
            subset = df[(df["kick_distance"] >= lo) & (df["kick_distance"] <= hi)]
            if len(subset) >= 30:
                rates[band] = float(subset["is_made"].mean())
    return rates


def mixture_make_probability(
    *,
    kicker_make_rate: float | None = None,
    weather_mult: float = 1.0,
    band_rates: Mapping[str, float] | None = None,
    distance_weights: Sequence[tuple[float, float]] | None = None,
) -> float:
    """
    Expected make% = Σ w_d · P(make|d), optionally blended with kicker career rate.
    """
    rates = dict(band_rates or band_make_rates_from_history())
    weights = list(distance_weights or _DISTANCE_WEIGHTS)
    total_w = sum(w for _, w in weights) or 1.0
    mixture = 0.0
    for dist, w in weights:
        band = _distance_band(dist)
        mixture += (w / total_w) * float(rates.get(band, _BAND_PRIORS.get(band, 0.75)))
    mixture = max(0.05, min(0.99, mixture * weather_mult))
    if kicker_make_rate is None:
        return float(mixture)
    k = max(0.55, min(0.98, float(kicker_make_rate)))
    return float(0.7 * mixture + 0.3 * k)


def estimate_attempts_heuristic(
    team_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
) -> float:
    """
    FG attempts regressor (heuristic coefficients fit to league averages).

    Prefer this over a flat 1.85 when ML attempt model is absent.
    """
    team = dict(team_data or {})
    weather = dict(weather_data or {})
    base = 1.85

    rz_eff = float(team.get("team_red_zone_efficiency") or 60)
    third = float(team.get("third_down_conversion_rate") or 40)
    pace = float(team.get("plays_per_game") or team.get("pace") or 64)
    implied = team.get("implied_team_total")
    script = float(team.get("spread") or 0)  # negative = favored

    # Inefficient RZ → more FGs; efficient → more TDs
    base *= 1.0 + 0.004 * (60.0 - rz_eff)
    base *= 1.0 + 0.003 * (40.0 - third)
    # Faster pace → slightly more scoring drives / FG chances
    base *= 1.0 + 0.004 * (pace - 64.0)
    if implied is not None:
        # Mid totals drive FGs; very high totals skew TD-heavy
        imp = float(implied)
        if imp >= 28:
            base *= 0.92
        elif imp <= 18:
            base *= 0.95
        else:
            base *= 1.0 + 0.01 * (23.0 - abs(imp - 23.0)) / 5.0
    # Large favorites may run more → fewer FG attempts late
    if script <= -7:
        base *= 0.94
    elif script >= 7:
        base *= 1.04

    temp = weather.get("temperature")
    wind = weather.get("wind_speed")
    if temp is not None and float(temp) < 35:
        base *= 1.05
    if wind is not None and float(wind) > 18:
        base *= 0.95

    return float(min(2.8, max(1.1, base)))


def resolve_attempts(
    team_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
    *,
    attempts: float | None = None,
    season: int | None = None,
    week: int | None = None,
) -> tuple[float, str]:
    """Prefer explicit attempts → ML regressor → heuristic."""
    if attempts is not None:
        return float(min(3.0, max(1.0, attempts))), "explicit"
    try:
        from app.services.etl.nfl.kicker_attempts import estimate_attempts

        return estimate_attempts(team_data, weather_data, season=season, week=week)
    except Exception:
        return estimate_attempts_heuristic(team_data, weather_data), "heuristic"


def expected_fg_made(
    *,
    attempts: float | None = None,
    make_prob: float | None = None,
    team_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
    kicker_make_rate: float | None = None,
    classifier_make_prob: float | None = None,
    season: int | None = None,
    week: int | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    E[FG] = attempts × make%.

    Make% blends distance mixture with optional binary classifier probability.
    """
    att, att_source = resolve_attempts(
        team_data,
        weather_data,
        attempts=attempts,
        season=season,
        week=week,
    )
    att = max(1.0, min(3.0, att))

    weather_mult = 1.0
    if weather_data:
        wind = weather_data.get("wind_speed")
        temp = weather_data.get("temperature")
        is_dome = False
        if team_data:
            is_dome = str(team_data.get("venue_type") or "").lower() == "dome"
        try:
            wind_f = float(wind) if wind is not None else None
        except (TypeError, ValueError):
            wind_f = None
        try:
            temp_f = float(temp) if temp is not None else None
        except (TypeError, ValueError):
            temp_f = None
        weather_mult = weather_make_multiplier(
            wind_speed=wind_f,
            temperature=temp_f,
            is_dome=is_dome,
        )

    mixture = mixture_make_probability(
        kicker_make_rate=kicker_make_rate,
        weather_mult=weather_mult,
    )
    if classifier_make_prob is not None:
        make = 0.55 * float(classifier_make_prob) + 0.45 * mixture
    elif make_prob is not None:
        make = float(make_prob)
    else:
        make = mixture
    make = max(0.05, min(0.99, make))
    projected = round(att * make, 2)
    meta = {
        "projected_attempts": round(att, 2),
        "attempts_source": att_source,
        "make_probability": round(make, 3),
        "mixture_make_probability": round(mixture, 3),
        "volume_model": "attempts_x_distance_mixture",
    }
    if classifier_make_prob is not None:
        meta["classifier_make_probability"] = round(float(classifier_make_prob), 3)
    return projected, meta


def walk_forward_default_blend_from_fg_csv(
    *,
    weight_grid: Sequence[float] | None = None,
) -> float:
    """
    Offline proxy tune: treat statistical heuristic vs mixture volume on CSV
    game aggregates when actual prediction logs are unavailable.
    """
    from app.services.etl.nfl.kicker_blend_tune import walk_forward_blend_weight

    df = _load_fg_history()
    if df is None or df.empty:
        return 0.30
    need = {"game_id", "is_made"}
    if not need.issubset(df.columns):
        return 0.30
    games = (
        df.groupby("game_id", as_index=False)
        .agg(actual_fg_made=("is_made", "sum"), n_att=("is_made", "count"))
        .sort_values("game_id")
    )
    if len(games) < 40:
        return 0.30
    records = []
    mix = mixture_make_probability()
    for _, row in games.iterrows():
        att = float(row["n_att"])
        # Proxy "statistical" as league prior attempts * mixture; ML as att*mix
        # (same game — this is a weak proxy; prefer prod walk-forward).
        statistical = 1.85 * mix
        ml = min(3.0, att) * mix
        records.append(
            {
                "statistical_fgs": statistical,
                "ml_fgs": ml,
                "actual_fg_made": float(row["actual_fg_made"]),
            }
        )
    grid = (
        list(weight_grid)
        if weight_grid is not None
        else [round(w, 2) for w in np.arange(0.0, 0.55, 0.05)]
    )
    return float(walk_forward_blend_weight(records, weight_grid=grid, min_train=20))
