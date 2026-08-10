"""Shared Elo + pace-overlay spread math for basketball leagues."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class SpreadLeagueConfig:
    initial_elo: float = 1500.0
    elo_k: float = 20.0
    home_court_advantage: float = 2.5
    spread_per_elo: float = 25.0
    win_prob_logistic_scale: float = 7.0
    edge_threshold: float = 2.0
    pace_overlay_factor: float = 0.15


WNBA_CONFIG = SpreadLeagueConfig(home_court_advantage=2.5)
NBA_CONFIG = SpreadLeagueConfig(home_court_advantage=2.8)
NFL_CONFIG = SpreadLeagueConfig(home_court_advantage=2.5, edge_threshold=3.0)


class SpreadActualRow(Protocol):
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_elo(
    home_elo: float,
    away_elo: float,
    home_score: int,
    away_score: int,
    *,
    cfg: SpreadLeagueConfig = WNBA_CONFIG,
) -> tuple[float, float]:
    home_won = 1.0 if home_score > away_score else 0.0
    expected_home = expected_score(
        home_elo + cfg.home_court_advantage * cfg.spread_per_elo, away_elo
    )
    delta = cfg.elo_k * (home_won - expected_home)
    return home_elo + delta, away_elo - delta


def expected_margin(
    home_elo: float, away_elo: float, *, cfg: SpreadLeagueConfig = WNBA_CONFIG
) -> float:
    elo_diff_margin = (home_elo - away_elo) / cfg.spread_per_elo
    return elo_diff_margin + cfg.home_court_advantage


def margin_to_win_prob(
    margin: float, *, cfg: SpreadLeagueConfig = WNBA_CONFIG
) -> float:
    return 1.0 / (1.0 + math.exp(-margin / cfg.win_prob_logistic_scale))


def pace_overlay_adjustment(
    home_off: float | None,
    home_def: float | None,
    away_off: float | None,
    away_def: float | None,
    *,
    cfg: SpreadLeagueConfig = WNBA_CONFIG,
) -> float:
    if None in (home_off, home_def, away_off, away_def):
        return 0.0
    home_advantage = (home_off - away_def) - (away_off - home_def)
    return home_advantage * cfg.pace_overlay_factor


def load_elos_from_actuals(
    actuals: Sequence[SpreadActualRow],
    *,
    cfg: SpreadLeagueConfig = WNBA_CONFIG,
) -> dict[str, float]:
    elos: dict[str, float] = {}
    for game in actuals:
        h = elos.setdefault(game.home_team_name, cfg.initial_elo)
        a = elos.setdefault(game.away_team_name, cfg.initial_elo)
        new_h, new_a = update_elo(h, a, game.home_score, game.away_score, cfg=cfg)
        elos[game.home_team_name] = new_h
        elos[game.away_team_name] = new_a
    return elos


def spread_recommendation(
    projected_margin: float,
    market_spread_home: float | None,
    *,
    cfg: SpreadLeagueConfig = WNBA_CONFIG,
) -> tuple[float | None, str]:
    if market_spread_home is None:
        return None, "NO_PLAY"
    implied_market_margin = -market_spread_home
    edge = projected_margin - implied_market_margin
    if edge >= cfg.edge_threshold:
        return edge, "HOME"
    if edge <= -cfg.edge_threshold:
        return edge, "AWAY"
    return edge, "NO_PLAY"
