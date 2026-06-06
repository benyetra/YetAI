"""Shared WNBA expected-minutes calculations (live + historical training)."""

from __future__ import annotations

import math
from datetime import date

LOOKBACK_GAMES = 30
MIN_GAMES_REQUIRED = 5

# Recency weights for last 10 games (most recent first).
RECENCY_WEIGHTS = [0.25, 0.20, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05, 0.025, 0.025]


def calc_metrics(games: list) -> dict | None:
    """Pure minutes metrics from recent games (newest first, minutes > 0)."""
    playable = [g for g in games if getattr(g, "minutes", None) not in (None, 0)]
    if len(playable) < MIN_GAMES_REQUIRED:
        return None

    all_minutes = [float(g.minutes) for g in playable]
    last_5 = all_minutes[:5]
    last_10 = all_minutes[:10]

    avg_5 = sum(last_5) / len(last_5)
    avg_10 = sum(last_10) / len(last_10)

    variance = sum((x - avg_10) ** 2 for x in last_10) / len(last_10)
    std_dev = math.sqrt(variance)

    b2b_minutes: list[float] = []
    for i in range(len(playable) - 1):
        if (playable[i].game_date - playable[i + 1].game_date).days == 1:
            b2b_minutes.append(float(playable[i].minutes))
    b2b_avg = sum(b2b_minutes) / len(b2b_minutes) if b2b_minutes else None

    home = [float(g.minutes) for g in playable if g.home_game is True]
    away = [float(g.minutes) for g in playable if g.home_game is False]
    home_avg = sum(home) / len(home) if len(home) >= 3 else None
    away_avg = sum(away) / len(away) if len(away) >= 3 else None

    weighted_sum = 0.0
    total_weight = 0.0
    for i, minutes in enumerate(last_10):
        weight = RECENCY_WEIGHTS[i] if i < len(RECENCY_WEIGHTS) else 0.01
        weighted_sum += minutes * weight
        total_weight += weight
    expected = weighted_sum / total_weight if total_weight else avg_10

    return {
        "avg_minutes_5": avg_5,
        "avg_minutes_10": avg_10,
        "expected_base": expected,
        "b2b_minutes_avg": b2b_avg,
        "home_minutes_avg": home_avg,
        "away_minutes_avg": away_avg,
        "minutes_std_dev": std_dev,
        "last_game_date": playable[0].game_date,
    }


def apply_context_adjustments(
    metrics: dict,
    *,
    game_date: date,
    home_game: bool | None,
) -> float:
    """Blend weighted baseline with B2B and home/away splits for target game."""
    expected = metrics["expected_base"]

    days_rest = (game_date - metrics["last_game_date"]).days
    if days_rest <= 1:
        b2b_avg = metrics.get("b2b_minutes_avg")
        expected = (
            0.7 * expected + 0.3 * b2b_avg if b2b_avg is not None else expected * 0.95
        )

    home_avg = metrics.get("home_minutes_avg")
    away_avg = metrics.get("away_minutes_avg")
    if home_game is True and home_avg is not None:
        expected = 0.9 * expected + 0.1 * home_avg
    elif home_game is False and away_avg is not None:
        expected = 0.9 * expected + 0.1 * away_avg

    return expected


def historical_expected_minutes(
    games_before: list,
    *,
    game_date: date,
    home_game: bool | None,
) -> float | None:
    """Expected minutes for a past game using only prior box scores."""
    metrics = calc_metrics(games_before)
    if metrics is None:
        return None
    return round(
        max(
            0.0,
            apply_context_adjustments(
                metrics, game_date=game_date, home_game=home_game
            ),
        ),
        1,
    )


def is_home_bool(is_home_feature: float, *, team_name: str) -> bool | None:
    """Convert game-line is_home feature to bool for context adjustments."""
    if not team_name:
        return None
    if is_home_feature >= 0.5:
        return True
    return False
