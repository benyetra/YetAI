"""Shared NFLGameLines lookup for the NFL sources (prices, teams, kickoff)."""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import NFLGameLines

log = logging.getLogger(__name__)


def load_nfl_lines(db: Session, game_date: date) -> list[NFLGameLines]:
    return db.query(NFLGameLines).filter(NFLGameLines.game_date == game_date).all()


def find_line(
    lines: list[NFLGameLines], *team_names: str | None
) -> NFLGameLines | None:
    """Game whose home or away team is any of ``team_names`` (full names)."""
    wanted = {t for t in team_names if t}
    for gl in lines:
        if gl.home_team_name in wanted or gl.away_team_name in wanted:
            return gl
    return None


def line_event_id(gl: NFLGameLines) -> str:
    return (
        gl.odds_api_event_id
        or f"nfl-{gl.game_date}-{gl.home_team_name}-{gl.away_team_name}"
    )
