"""Seed NFL Elo ratings from historical game results."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Sequence

import nfl_data_py as nfl
import pandas as pd

from app.services.etl._spread_model import (
    NFL_CONFIG,
    SpreadActualRow,
    SpreadLeagueConfig,
    load_elos_from_actuals,
)
from app.services.etl.nfl.team_names import normalize_team_name

DEFAULT_SEED_SEASONS: tuple[int, ...] = (2023, 2024, 2025)


def seed_elos_from_games(
    games: Sequence[SpreadActualRow],
    *,
    cfg: SpreadLeagueConfig = NFL_CONFIG,
) -> dict[str, float]:
    """Replay completed games chronologically to derive Elo ratings."""
    return load_elos_from_actuals(games, cfg=cfg)


def fetch_reg_games_nflverse(seasons: list[int] | None = None) -> list[SimpleNamespace]:
    """Load completed REG games; normalize team names; skip missing scores."""
    resolved = list(seasons if seasons is not None else DEFAULT_SEED_SEASONS)
    if not resolved:
        return []

    schedules = nfl.import_schedules(resolved)
    if schedules.empty:
        return []

    reg = schedules
    if "game_type" in reg.columns:
        reg = reg[reg["game_type"] == "REG"]

    reg = reg.dropna(subset=["home_score", "away_score"])
    if reg.empty:
        return []

    sort_cols = [c for c in ("gameday", "gametime", "game_id") if c in reg.columns]
    if sort_cols:
        reg = reg.sort_values(sort_cols)

    games: list[SimpleNamespace] = []
    for row in reg.itertuples(index=False):
        home_score = getattr(row, "home_score", None)
        away_score = getattr(row, "away_score", None)
        if pd.isna(home_score) or pd.isna(away_score):
            continue
        games.append(
            SimpleNamespace(
                home_team_name=normalize_team_name(str(row.home_team)),
                away_team_name=normalize_team_name(str(row.away_team)),
                home_score=int(home_score),
                away_score=int(away_score),
            )
        )
    return games
