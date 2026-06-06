"""Admin bet-entry odds from pred_*_game_lines when live Odds API is unavailable."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, WNBAGameLines
from app.services.wnba_admin_odds_fallback import bookmakers_from_game_line

_LINE_MODELS: dict[str, tuple[type, str, str, str]] = {
    "basketball_wnba": (WNBAGameLines, "basketball_wnba", "WNBA", "wnba"),
    "basketball_nba": (NBAGameLines, "basketball_nba", "NBA", "nba"),
}


def game_has_betting_markets(game: dict[str, Any]) -> bool:
    for bookmaker in game.get("bookmakers") or []:
        for market in bookmaker.get("markets") or []:
            if market.get("outcomes"):
                return True
    return False


def _row_to_game_dict(
    row: Any,
    *,
    sport_key: str,
    sport_title: str,
    id_prefix: str,
) -> dict[str, Any]:
    from app.services.etl.wnba._espn import EASTERN

    commence = row.game_time
    if commence is None:
        commence = datetime.combine(
            row.game_date, time(19, 0), tzinfo=EASTERN
        ).astimezone(timezone.utc)
    elif commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    else:
        commence = commence.astimezone(timezone.utc)

    event_id = row.odds_api_event_id
    if not event_id:
        slug_home = (row.home_team_name or "home").replace(" ", "-")
        slug_away = (row.away_team_name or "away").replace(" ", "-")
        event_id = f"{id_prefix}-{row.game_date}-{slug_away}-at-{slug_home}"

    return {
        "id": event_id,
        "sport_key": sport_key,
        "sport_title": sport_title,
        "commence_time": commence.isoformat().replace("+00:00", "Z"),
        "home_team": row.home_team_name,
        "away_team": row.away_team_name,
        "bookmakers": bookmakers_from_game_line(row),
    }


def games_from_pred_lines(
    sport_key: str,
    *,
    days_ahead: int = 14,
    db: Optional[Session] = None,
) -> list[dict[str, Any]]:
    """Upcoming slates from pred_*_game_lines for admin game/prop pickers."""
    if sport_key == "baseball_mlb":
        from app.services.mlb_admin_odds_fallback import (
            games_from_pred_game_projections,
        )

        return games_from_pred_game_projections(days_ahead=days_ahead, db=db)

    if sport_key not in _LINE_MODELS:
        return []

    model, sk, title, id_prefix = _LINE_MODELS[sport_key]
    from app.core.database import SessionLocal
    from app.services.etl.wnba._espn import now_eastern

    today = now_eastern().date()
    end = today + timedelta(days=days_ahead)
    own_session = db is None
    if own_session:
        db = SessionLocal()
    assert db is not None
    try:
        rows = (
            db.query(model)
            .filter(model.game_date >= today, model.game_date <= end)
            .order_by(model.game_date, model.game_time)
            .all()
        )
    except Exception:
        return []
    finally:
        if own_session:
            db.close()

    return [
        _row_to_game_dict(row, sport_key=sk, sport_title=title, id_prefix=id_prefix)
        for row in rows
    ]


def _lookup_line_row(
    db: Session,
    sport_key: str,
    game: dict[str, Any],
) -> Any | None:
    if sport_key not in _LINE_MODELS:
        return None
    model, _, _, _ = _LINE_MODELS[sport_key]
    event_id = game.get("id")
    if event_id:
        row = (
            db.query(model)
            .filter(model.odds_api_event_id == event_id)
            .order_by(model.game_date.desc())
            .first()
        )
        if row:
            return row
    home = game.get("home_team")
    away = game.get("away_team")
    if home and away:
        from app.services.etl.wnba._espn import now_eastern

        today = now_eastern().date()
        return (
            db.query(model)
            .filter(
                model.game_date >= today,
                model.home_team_name == home,
                model.away_team_name == away,
            )
            .order_by(model.game_date)
            .first()
        )
    return None


def enrich_games_with_pred_lines(
    sport_key: str,
    games: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach consensus bookmakers from DB when live/cached games lack markets."""
    if not games:
        return games

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        enriched: list[dict[str, Any]] = []
        for game in games:
            if game_has_betting_markets(game):
                enriched.append(game)
                continue
            if sport_key == "baseball_mlb":
                from app.services.mlb_admin_odds_fallback import (
                    bookmakers_from_game_projection,
                    lookup_projection_for_game,
                )

                row = lookup_projection_for_game(db, game)
                if row:
                    bookmakers = bookmakers_from_game_projection(row)
                    if bookmakers:
                        enriched.append({**game, "bookmakers": bookmakers})
                        continue
            elif sport_key in _LINE_MODELS:
                row = _lookup_line_row(db, sport_key, game)
                if row:
                    bookmakers = bookmakers_from_game_line(row)
                    if bookmakers:
                        enriched.append({**game, "bookmakers": bookmakers})
                        continue
            enriched.append(game)
        return enriched
    finally:
        db.close()
