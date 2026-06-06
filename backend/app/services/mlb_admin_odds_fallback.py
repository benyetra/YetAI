"""Admin UI fallbacks when live Odds API is unavailable for MLB."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import GameProjections, Pitcher, StrikeoutProjections

_CONSENSUS_KEY = "consensus"
_CONSENSUS_TITLE = "Consensus (pred_game_projections)"


def _american_or_none(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_id_for_projection(row: GameProjections) -> str:
    slug_home = (row.home_team or "home").replace(" ", "-")
    slug_away = (row.away_team or "away").replace(" ", "-")
    return f"mlb-{row.date}-{slug_away}-at-{slug_home}"


def bookmakers_from_game_projection(row: GameProjections) -> list[dict[str, Any]]:
    """Shape pred_game_projections market fields into Odds API-like bookmakers."""
    markets: list[dict[str, Any]] = []

    if row.market_spread is not None:
        spread_home = float(row.market_spread)
        spread_away = -spread_home
        markets.append(
            {
                "key": "spreads",
                "outcomes": [
                    {
                        "name": row.home_team,
                        "price": -110,
                        "point": spread_home,
                    },
                    {
                        "name": row.away_team,
                        "price": -110,
                        "point": spread_away,
                    },
                ],
            }
        )

    if row.market_home_ml is not None or row.market_away_ml is not None:
        h2h = []
        if row.market_home_ml is not None:
            h2h.append(
                {
                    "name": row.home_team,
                    "price": int(row.market_home_ml),
                }
            )
        if row.market_away_ml is not None:
            h2h.append(
                {
                    "name": row.away_team,
                    "price": int(row.market_away_ml),
                }
            )
        if h2h:
            markets.append({"key": "h2h", "outcomes": h2h})

    if row.market_total is not None:
        markets.append(
            {
                "key": "totals",
                "outcomes": [
                    {
                        "name": "Over",
                        "price": -110,
                        "point": float(row.market_total),
                    },
                    {
                        "name": "Under",
                        "price": -110,
                        "point": float(row.market_total),
                    },
                ],
            }
        )

    if not markets:
        return []

    stamp = row.updated_at or row.created_at
    return [
        {
            "key": _CONSENSUS_KEY,
            "title": _CONSENSUS_TITLE,
            "last_update": (
                stamp.isoformat() if stamp else datetime.now(timezone.utc).isoformat()
            ),
            "markets": markets,
        }
    ]


def _projection_to_game_dict(row: GameProjections) -> dict[str, Any]:
    commence = row.game_time
    if commence is None:
        commence = datetime.combine(row.date, time(19, 0), tzinfo=timezone.utc)
    elif commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    else:
        commence = commence.astimezone(timezone.utc)

    return {
        "id": event_id_for_projection(row),
        "sport_key": "baseball_mlb",
        "sport_title": "MLB",
        "commence_time": commence.isoformat().replace("+00:00", "Z"),
        "home_team": row.home_team,
        "away_team": row.away_team,
        "bookmakers": bookmakers_from_game_projection(row),
    }


def games_from_pred_game_projections(
    *,
    days_ahead: int = 14,
    db: Optional[Session] = None,
) -> list[dict[str, Any]]:
    """Upcoming MLB slates from pred_game_projections for admin pickers."""
    from app.core.database import SessionLocal

    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days_ahead)
    own_session = db is None
    if own_session:
        db = SessionLocal()
    assert db is not None
    try:
        rows = (
            db.query(GameProjections)
            .filter(GameProjections.date >= today, GameProjections.date <= end)
            .order_by(GameProjections.date, GameProjections.game_time)
            .all()
        )
    except Exception:
        return []
    finally:
        if own_session:
            db.close()

    games = [_projection_to_game_dict(row) for row in rows]
    return [g for g in games if g.get("bookmakers")]


def _find_game_projection(
    db: Session,
    *,
    event_id: str,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    game_date: Optional[date] = None,
) -> Optional[GameProjections]:
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=14)
    rows = (
        db.query(GameProjections)
        .filter(GameProjections.date >= today, GameProjections.date <= end)
        .order_by(GameProjections.date, GameProjections.game_time)
        .all()
    )
    for row in rows:
        if event_id_for_projection(row) == event_id:
            return row
    if home_team and away_team:
        target_date = game_date or today
        for row in rows:
            if (
                row.home_team == home_team
                and row.away_team == away_team
                and row.date == target_date
            ):
                return row
    return None


def lookup_projection_for_game(
    db: Session,
    game: dict[str, Any],
) -> Optional[GameProjections]:
    event_id = game.get("id")
    if not event_id:
        return None
    return _find_game_projection(
        db,
        event_id=event_id,
        home_team=game.get("home_team"),
        away_team=game.get("away_team"),
    )


def mlb_player_props_from_projections(
    db: Session,
    *,
    event_id: str,
    game_date: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Build player-props payload from MLB projection tables (no Odds API)."""
    projection = _find_game_projection(db, event_id=event_id, game_date=game_date)
    if not projection:
        return None

    target_date = game_date or projection.date
    game_id = projection.game_id
    stamp = datetime.now(timezone.utc).isoformat()
    players: list[dict[str, Any]] = []

    strikeout_rows = (
        db.query(StrikeoutProjections)
        .filter(StrikeoutProjections.date == target_date)
        .all()
    )
    pitcher_rows = db.query(Pitcher).filter(Pitcher.game_id == game_id).all()
    pitcher_by_id = {p.pitcher_id: p for p in pitcher_rows}

    for row in strikeout_rows:
        pitcher = pitcher_by_id.get(row.pitcher_id)
        if pitcher is None:
            continue
        line_val = row.fanduel_line
        if line_val is None or line_val <= 0:
            fd_point = getattr(pitcher, "fanduel_point", None)
            if fd_point is not None and fd_point > 0:
                line_val = float(fd_point)
        if line_val is None or line_val <= 0:
            continue
        over_odds = _american_or_none(
            int(pitcher.fanduel_price) if pitcher.fanduel_price else None
        )
        players.append(
            {
                "player_name": row.pitcher_name or pitcher.name,
                "line": float(line_val),
                "over": over_odds if over_odds is not None else -110,
                "under": None,
            }
        )

    if not players:
        return None

    return {
        "event_id": event_id,
        "sport_key": "baseball_mlb",
        "sport_title": "MLB",
        "home_team": projection.home_team,
        "away_team": projection.away_team,
        "markets": {
            "pitcher_strikeouts": {
                "market_key": "pitcher_strikeouts",
                "last_update": stamp,
                "players": players,
            }
        },
        "source": "pred_mlb_prop_projections",
    }
