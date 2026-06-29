"""MLB YetiWatch adapter — probable starters on today's slate."""

from __future__ import annotations

from datetime import date, datetime

import statsapi
from sqlalchemy.orm import Session

from app.services.etl.mlb.injury_tracker import fetch_team_roster_il
from app.services.etl.mlb.strikeouts import get_todays_games
from app.services.etl.nba._espn import now_eastern
from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.yetiwatch.slate import SlateSubject


def _resolve_pitcher_id(pitcher_name: str) -> str:
    try:
        matches = statsapi.lookup_player(pitcher_name)
        if matches:
            return str(matches[0]["id"])
    except Exception:
        pass
    return pitcher_name


class MLBAdapter:
    sport = "mlb"

    def game_date(self) -> date:
        return now_eastern().date()

    def load_slate(self, db: Session, game_date: date) -> list[SlateSubject]:
        subjects: list[SlateSubject] = []
        for game in get_todays_games() or []:
            for side in ("home", "away"):
                pitcher_name = game.get(f"{side}_probable_pitcher")
                if not pitcher_name:
                    continue
                team_id = game.get(f"{side}_id")
                opponent_id = game.get("away_id" if side == "home" else "home_id")
                entity_id = _resolve_pitcher_id(pitcher_name)
                subjects.append(
                    SlateSubject(
                        sport=self.sport,
                        entity_id=entity_id,
                        entity_name=pitcher_name,
                        team_id=str(team_id) if team_id is not None else None,
                        opponent_id=(
                            str(opponent_id) if opponent_id is not None else None
                        ),
                        game_date=game_date,
                    )
                )
        return subjects

    def fetch_candidate_items(self, db: Session) -> tuple[list[CandidateItem], bool]:
        now = datetime.utcnow()
        items: list[CandidateItem] = []
        team_ids: set[int] = set()
        for game in get_todays_games() or []:
            for key in ("home_id", "away_id"):
                tid = game.get(key)
                if tid is not None:
                    team_ids.add(int(tid))
        for team_id in team_ids:
            for row in fetch_team_roster_il(team_id):
                items.append(
                    CandidateItem(
                        tier=SourceTier.OFFICIAL,
                        source_label="MLB IL roster",
                        item_ts=now,
                        text=f"{row['status_code']} ({row.get('status_description', '')})".strip(),
                        player_name=row.get("player_name"),
                    )
                )
        return items, True

    def apply_signals(self, db: Session, game_date: date) -> dict:
        return {"status": "ok", "adjusted": 0, "reason": "mlb_no_minutes_apply"}
