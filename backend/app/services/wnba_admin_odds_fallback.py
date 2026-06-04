"""Admin UI fallbacks when live Odds API is unavailable for WNBA."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    WNBAAssistsProjections,
    WNBAGameLines,
    WNBAPointsProjections,
    WNBAReboundsProjections,
)

_CONSENSUS_KEY = "consensus"
_CONSENSUS_TITLE = "Consensus (pred_wnba_game_lines)"

_PROP_MODELS: dict[str, type] = {
    "player_points": WNBAPointsProjections,
    "player_rebounds": WNBAReboundsProjections,
    "player_assists": WNBAAssistsProjections,
}


def _american_or_none(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bookmakers_from_game_line(row: WNBAGameLines) -> list[dict[str, Any]]:
    """Shape pred_wnba_game_lines consensus into Odds API-like bookmakers for admin UI."""
    markets: list[dict[str, Any]] = []

    if row.spread_home is not None:
        spread_away = row.spread_away
        if spread_away is None and row.spread_home is not None:
            spread_away = -float(row.spread_home)
        outcomes = []
        if row.spread_home is not None:
            outcomes.append(
                {
                    "name": row.home_team_name,
                    "price": _american_or_none(row.spread_home_odds) or -110,
                    "point": float(row.spread_home),
                }
            )
        if spread_away is not None:
            outcomes.append(
                {
                    "name": row.away_team_name,
                    "price": _american_or_none(row.spread_away_odds) or -110,
                    "point": float(spread_away),
                }
            )
        if outcomes:
            markets.append({"key": "spreads", "outcomes": outcomes})

    if row.moneyline_home is not None or row.moneyline_away is not None:
        h2h = []
        if row.moneyline_home is not None:
            h2h.append(
                {
                    "name": row.home_team_name,
                    "price": int(row.moneyline_home),
                }
            )
        if row.moneyline_away is not None:
            h2h.append(
                {
                    "name": row.away_team_name,
                    "price": int(row.moneyline_away),
                }
            )
        if h2h:
            markets.append({"key": "h2h", "outcomes": h2h})

    if row.total is not None:
        totals = []
        if row.over_odds is not None:
            totals.append(
                {
                    "name": "Over",
                    "price": int(row.over_odds),
                    "point": float(row.total),
                }
            )
        if row.under_odds is not None:
            totals.append(
                {
                    "name": "Under",
                    "price": int(row.under_odds),
                    "point": float(row.total),
                }
            )
        if not totals:
            totals = [
                {"name": "Over", "price": -110, "point": float(row.total)},
                {"name": "Under", "price": -110, "point": float(row.total)},
            ]
        markets.append({"key": "totals", "outcomes": totals})

    if not markets:
        return []

    return [
        {
            "key": _CONSENSUS_KEY,
            "title": _CONSENSUS_TITLE,
            "last_update": (
                row.last_updated.isoformat()
                if row.last_updated
                else datetime.now(timezone.utc).isoformat()
            ),
            "markets": markets,
        }
    ]


def wnba_player_props_from_projections(
    db: Session,
    *,
    event_id: str,
    game_date: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Build player-props payload from WNBA projection tables (no Odds API)."""
    line = (
        db.query(WNBAGameLines)
        .filter(WNBAGameLines.odds_api_event_id == event_id)
        .order_by(WNBAGameLines.game_date.desc())
        .first()
    )
    if not line:
        return None

    target_date = game_date or line.game_date
    markets: dict[str, Any] = {}
    stamp = datetime.now(timezone.utc).isoformat()

    teams = {line.home_team_name, line.away_team_name}
    for market_key, model in _PROP_MODELS.items():
        rows = (
            db.query(model)
            .filter(
                model.date == target_date,
                model.market_line.isnot(None),
                model.opponent_team_name.in_(teams),
            )
            .all()
        )
        players = []
        for row in rows:
            players.append(
                {
                    "player_name": row.player_name or f"Player {row.player_id}",
                    "line": float(row.market_line),
                    "over": -110,
                    "under": None,
                }
            )
        if players:
            markets[market_key] = {
                "market_key": market_key,
                "last_update": stamp,
                "players": players,
            }

    if not markets:
        return None

    return {
        "event_id": event_id,
        "sport_key": "basketball_wnba",
        "sport_title": "WNBA",
        "home_team": line.home_team_name,
        "away_team": line.away_team_name,
        "markets": markets,
        "source": "pred_wnba_prop_projections",
    }
