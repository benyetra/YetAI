"""Attach FanDuel player-prop lines from The Odds API for WNBA projections.

Uses the same market keys as NBA (player_points, player_rebounds, player_assists)
for sport ``basketball_wnba``. See:
https://the-odds-api.com/sports-odds-data/betting-markets.html

Event IDs are resolved from ``pred_wnba_game_lines.odds_api_event_id`` when
available (populated by the thrice-daily ``update_game_lines`` task), then fall
back to the live /events list with canonical team-name normalization.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBAGameLines
from app.services.etl.nba._fanduel_lines import (
    PROP_MARKETS,
    fetch_fanduel_prop_for_player,
    get_event_id_for_game,
)
from app.services.player_prop_projection_display import prop_confidence_pct

WNBA_SPORT = "basketball_wnba"

logger = logging.getLogger(__name__)

# FanDuel often has thin WNBA prop books; include common US books in one request.
WNBA_PROP_BOOKMAKERS = "fanduel,draftkings,betmgm"

# Minimum |projected - line| to emit OVER/UNDER (stat-specific).
EDGE_THRESHOLDS: dict[str, float] = {
    "points": 1.0,
    "assists": 0.5,
    "rebounds": 0.5,
    "three_pt_made": 0.5,
    "pra": 1.5,
}


def _matchup_team_pair(team_name: str, opponent_team_name: str) -> set[str] | None:
    """Return canonical {team, opponent} names, or None when inputs are invalid."""
    if not isinstance(team_name, str) or not isinstance(opponent_team_name, str):
        return None
    home = team_name.strip()
    away = (opponent_team_name or "").strip()
    if not home or not away or home == away:
        return None
    return {home, away}


def lookup_wnba_event_id(
    db: Session,
    game_date: date,
    team_name: str,
    opponent_team_name: str,
) -> str | None:
    """Match today's game row and return stored Odds API event id."""
    pair = _matchup_team_pair(team_name, opponent_team_name)
    if pair is None:
        return None
    rows = (
        db.query(
            WNBAGameLines.odds_api_event_id,
            WNBAGameLines.home_team_name,
            WNBAGameLines.away_team_name,
        )
        .filter(WNBAGameLines.game_date == game_date)
        .all()
    )
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            continue
        event_id, home, away = row
        if event_id and {home, away} == pair:
            return event_id
    return None


def resolve_wnba_event_id(
    db: Session,
    game_date: date,
    team_name: str,
    opponent_team_name: str,
) -> str | None:
    """Prefer DB-backed event id; fall back to live /events team matching."""
    event_id = lookup_wnba_event_id(db, game_date, team_name, opponent_team_name)
    if event_id:
        return event_id
    return get_event_id_for_game(WNBA_SPORT, team_name, opponent_team_name)


def _edge_and_recommendation(
    projected: float, line: float, threshold: float
) -> tuple[float, str]:
    edge = round(projected - line, 2)
    if abs(edge) < threshold:
        return edge, "NO_PLAY"
    return edge, "OVER" if edge > 0 else "UNDER"


def attach_prop_market_fields(
    row: dict[str, Any],
    *,
    db: Session,
    game_date: date,
    team_name: str,
    opponent_team_name: str,
    player_name: str,
    stat: str,
    projected: float,
    event_id: str | None = None,
) -> bool:
    """Set market_line, edge, and recommendation on a projection upsert row.

    Returns True when a sportsbook line was attached.
    """
    market = PROP_MARKETS.get(stat)
    if not market:
        return False

    if not event_id:
        event_id = resolve_wnba_event_id(db, game_date, team_name, opponent_team_name)

    line, _flag = fetch_fanduel_prop_for_player(
        team_name,
        opponent_team_name,
        player_name,
        market,
        projected,
        sport=WNBA_SPORT,
        event_id=event_id,
        bookmakers=WNBA_PROP_BOOKMAKERS,
    )
    if line is None:
        return False

    threshold = EDGE_THRESHOLDS.get(stat, 1.0)
    edge, recommendation = _edge_and_recommendation(projected, line, threshold)
    row["market_line"] = line
    row["edge"] = edge
    row["recommendation"] = recommendation
    row["confidence_score"] = (
        prop_confidence_pct(abs(edge), stat) if recommendation != "NO_PLAY" else None
    )
    return True
