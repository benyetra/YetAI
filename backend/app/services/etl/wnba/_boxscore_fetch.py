"""Fetch and merge WNBA traditional + advanced box scores for ETL."""

from __future__ import annotations

from datetime import date
from typing import Any

from nba_api.stats.endpoints import (  # type: ignore
    boxscoreadvancedv2,
    boxscoretraditionalv2,
)

from app.services.etl.wnba._shooting_metrics import enrich_boxscore_row
from app.services.etl.wnba._wnba_stats import _resolve_profile, _retry


def _minutes_to_float(minutes_str: str | None) -> float | None:
    """MIN format is 'MM:SS' or 'MM.SS'. Return total minutes as float."""
    if not minutes_str:
        return None
    s = str(minutes_str).strip()
    try:
        if ":" in s:
            m, sec = s.split(":")
            return float(m) + float(sec) / 60.0
        return float(s)
    except (ValueError, AttributeError):
        return None


def fetch_traditional_boxscore(
    game_id: str, *, profile: str = "default"
) -> list[dict[str, Any]]:
    cfg = _resolve_profile(profile)

    def call() -> list[dict[str, Any]]:
        obj = boxscoretraditionalv2.BoxScoreTraditionalV2(
            game_id=game_id, timeout=cfg.timeout
        )
        return obj.get_normalized_dict()["PlayerStats"]

    return _retry(call, f"traditional_boxscore({game_id})", profile=profile)


def fetch_advanced_boxscore(
    game_id: str, *, profile: str = "backfill_advanced"
) -> list[dict[str, Any]]:
    cfg = _resolve_profile(profile)

    def call() -> list[dict[str, Any]]:
        obj = boxscoreadvancedv2.BoxScoreAdvancedV2(
            game_id=game_id, timeout=cfg.timeout
        )
        return obj.get_normalized_dict()["PlayerStats"]

    return _retry(call, f"advanced_boxscore({game_id})", profile=profile)


def advanced_fields_from_row(row: dict[str, Any] | None) -> dict[str, float]:
    """Map BoxScoreAdvancedV2 columns; eFG/TS stay derived from traditional box."""
    if not row:
        return {}
    mapping = {
        "usage_percentage": row.get("USG_PCT"),
        "assist_percentage": row.get("AST_PCT"),
        "offensive_rating": row.get("OFF_RATING"),
        "defensive_rating": row.get("DEF_RATING"),
        "pace": row.get("PACE"),
        "possessions": row.get("POSS"),
        "net_rating": row.get("NET_RATING"),
    }
    out: dict[str, float] = {}
    for key, val in mapping.items():
        if val is not None:
            out[key] = float(val)
    return out


def player_game_row_from_boxscore(
    trad_row: dict[str, Any],
    *,
    game_date: date,
    opponent_team_id: int,
    home_game: bool | None,
    adv_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one upsert dict from traditional (+ optional advanced) API rows."""
    base: dict[str, Any] = {
        "player_id": int(trad_row["PLAYER_ID"]),
        "game_date": game_date,
        "opponent_team_id": opponent_team_id,
        "points": trad_row.get("PTS"),
        "fg_attempts": trad_row.get("FGA"),
        "fg_percentage": trad_row.get("FG_PCT"),
        "three_pt_attempts": trad_row.get("FG3A"),
        "three_pt_percentage": trad_row.get("FG3_PCT"),
        "three_pt_made": trad_row.get("FG3M"),
        "ft_attempts": trad_row.get("FTA"),
        "ft_percentage": trad_row.get("FT_PCT"),
        "minutes": _minutes_to_float(trad_row.get("MIN")),
        "field_goals_made": trad_row.get("FGM"),
        "free_throws_made": trad_row.get("FTM"),
        "offensive_rebounds": trad_row.get("OREB"),
        "defensive_rebounds": trad_row.get("DREB"),
        "rebounds": trad_row.get("REB"),
        "assists": trad_row.get("AST"),
        "turnovers": trad_row.get("TOV"),
        "steals": trad_row.get("STL"),
        "blocks": trad_row.get("BLK"),
        "personal_fouls": trad_row.get("PF"),
        "home_game": home_game,
        "plus_minus": trad_row.get("PLUS_MINUS"),
    }
    base.update(advanced_fields_from_row(adv_row))
    return enrich_boxscore_row(base)


def advanced_by_player_id(adv_rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in adv_rows:
        pid = row.get("PLAYER_ID")
        if pid is not None:
            out[int(pid)] = row
    return out
