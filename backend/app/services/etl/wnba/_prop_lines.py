"""Attach FanDuel player-prop lines from The Odds API for WNBA projections.

Uses the same market keys as NBA (player_points, player_rebounds, player_assists)
for sport ``basketball_wnba``. See:
https://the-odds-api.com/sports-odds-data/betting-markets.html
"""

from __future__ import annotations

from typing import Any

from app.services.etl.nba._fanduel_lines import (
    PROP_MARKETS,
    fetch_fanduel_prop_for_player,
)

WNBA_SPORT = "basketball_wnba"

# Minimum |projected - line| to emit OVER/UNDER (stat-specific).
EDGE_THRESHOLDS: dict[str, float] = {
    "points": 1.0,
    "assists": 0.5,
    "rebounds": 0.5,
}


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
    team_name: str,
    opponent_team_name: str,
    player_name: str,
    stat: str,
    projected: float,
) -> bool:
    """Set market_line, edge, and recommendation on a projection upsert row.

    Returns True when a sportsbook line was attached.
    """
    market = PROP_MARKETS.get(stat)
    if not market:
        return False

    line, _flag = fetch_fanduel_prop_for_player(
        team_name,
        opponent_team_name,
        player_name,
        market,
        projected,
        sport=WNBA_SPORT,
    )
    if line is None:
        return False

    threshold = EDGE_THRESHOLDS.get(stat, 1.0)
    edge, recommendation = _edge_and_recommendation(projected, line, threshold)
    row["market_line"] = line
    row["edge"] = edge
    row["recommendation"] = recommendation
    return True
