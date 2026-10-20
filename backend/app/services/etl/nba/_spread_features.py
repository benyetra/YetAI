"""Game-level features for NBA spread ML.

Every feature is computed point-in-time from pred_nba_spread_actuals (games
before ``game_date``) plus that game's market line, so the training rows for
past seasons look exactly like what the projector feeds the model tonight.
Current-only tables (injuries, expected minutes, season team stats) have no
history and would skew training against serving, so they are not used.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Sequence

from app.services.etl._spread_model import (
    NBA_CONFIG,
    expected_margin,
    load_elos_from_actuals,
    pace_overlay_adjustment,
)

FORM_GAMES = 10
MAX_REST_DAYS = 7

# Feature order the model is trained on (stored in its metadata).
SPREAD_MODEL_FEATURES = [
    "elo_diff",
    "base_margin",
    "pace_adj",
    "elo_pace_margin",
    "home_ppg_l10",
    "away_ppg_l10",
    "home_papg_l10",
    "away_papg_l10",
    "home_margin_l10",
    "away_margin_l10",
    "home_rest_days",
    "away_rest_days",
    "rest_diff",
    "home_b2b",
    "away_b2b",
    "market_spread_home",
    "market_total",
]


def team_form(prior_actuals: Sequence, game_date: date) -> dict[str, dict]:
    """Per team: last-N points for/against, average margin and last game date."""
    games: dict[str, list[tuple[date, int, int]]] = defaultdict(list)
    for a in prior_actuals:
        games[a.home_team_name].append((a.game_date, a.home_score, a.away_score))
        games[a.away_team_name].append((a.game_date, a.away_score, a.home_score))
    form: dict[str, dict] = {}
    for team, rows in games.items():
        recent = rows[-FORM_GAMES:]
        n = len(recent)
        form[team] = {
            "ppg": sum(r[1] for r in recent) / n,
            "papg": sum(r[2] for r in recent) / n,
            "margin": sum(r[1] - r[2] for r in recent) / n,
            "last_game": rows[-1][0],
        }
    return form


def _rest_days(team_form_row: dict | None, game_date: date) -> float:
    if not team_form_row:
        return float(MAX_REST_DAYS)
    return float(min((game_date - team_form_row["last_game"]).days, MAX_REST_DAYS))


def _nan_if_none(value: float | None) -> float:
    return math.nan if value is None else float(value)


def compute_game_features(
    prior_actuals: Sequence,
    *,
    game_date: date,
    home_team_name: str,
    away_team_name: str,
    market_spread_home: float | None,
    market_total: float | None,
) -> dict[str, float]:
    """Pure feature vector; ``prior_actuals`` must be games before ``game_date``
    in date order. Missing market lines are NaN (XGBoost treats them as missing),
    never 0, which would read as a pick'em."""
    elos = load_elos_from_actuals(prior_actuals, cfg=NBA_CONFIG)
    home_elo = elos.get(home_team_name, NBA_CONFIG.initial_elo)
    away_elo = elos.get(away_team_name, NBA_CONFIG.initial_elo)
    base_margin = expected_margin(home_elo, away_elo, cfg=NBA_CONFIG)

    form = team_form(prior_actuals, game_date)
    home, away = form.get(home_team_name), form.get(away_team_name)
    pace_adj = pace_overlay_adjustment(
        home["ppg"] if home else None,
        home["papg"] if home else None,
        away["ppg"] if away else None,
        away["papg"] if away else None,
        cfg=NBA_CONFIG,
    )
    home_rest = _rest_days(home, game_date)
    away_rest = _rest_days(away, game_date)

    return {
        "elo_diff": home_elo - away_elo,
        "base_margin": base_margin,
        "pace_adj": pace_adj,
        "elo_pace_margin": base_margin + pace_adj,
        "home_ppg_l10": home["ppg"] if home else math.nan,
        "away_ppg_l10": away["ppg"] if away else math.nan,
        "home_papg_l10": home["papg"] if home else math.nan,
        "away_papg_l10": away["papg"] if away else math.nan,
        "home_margin_l10": home["margin"] if home else math.nan,
        "away_margin_l10": away["margin"] if away else math.nan,
        "home_rest_days": home_rest,
        "away_rest_days": away_rest,
        "rest_diff": home_rest - away_rest,
        "home_b2b": 1.0 if home_rest <= 1 else 0.0,
        "away_b2b": 1.0 if away_rest <= 1 else 0.0,
        "market_spread_home": _nan_if_none(market_spread_home),
        "market_total": _nan_if_none(market_total),
    }


def build_game_features(
    db,
    *,
    game_date: date,
    home_team_name: str,
    away_team_name: str,
    home_team_id: int | None,
    away_team_id: int | None,
    market_spread_home: float | None,
    market_total: float | None,
    spread_actuals_model,
) -> dict[str, float] | None:
    """Feature vector for one game, loading prior actuals from the database."""
    actuals = (
        db.query(spread_actuals_model)
        .filter(spread_actuals_model.game_date < game_date)
        .order_by(spread_actuals_model.game_date.asc())
        .all()
    )
    return compute_game_features(
        actuals,
        game_date=game_date,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        market_spread_home=market_spread_home,
        market_total=market_total,
    )
