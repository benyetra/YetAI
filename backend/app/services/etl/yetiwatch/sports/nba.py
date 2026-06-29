"""NBA YetiWatch adapter."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.predictions_models import PlayerInjuryStatus, TodayActivePlayers
from app.services.etl.nba._espn import now_eastern
from app.services.etl.yetiwatch.apply_signals import apply_signals_to_nba_slate
from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.yetiwatch.slate import SlateSubject


def _injury_text(status: str, injury_type: str | None) -> str:
    parts = [status]
    if injury_type:
        parts.append(f"({injury_type})")
    return " ".join(parts)


class NBAAdapter:
    sport = "nba"

    def game_date(self) -> date:
        return now_eastern().date()

    def load_slate(self, db: Session, game_date: date) -> list[SlateSubject]:
        rows = (
            db.query(TodayActivePlayers)
            .filter(TodayActivePlayers.game_date == game_date)
            .all()
        )
        return [
            SlateSubject(
                sport=self.sport,
                entity_id=str(row.player_id),
                entity_name=row.player_name,
                team_id=str(row.team_id),
                opponent_id=str(row.opponent_team_id),
                game_date=game_date,
                home_game=row.is_home_game,
            )
            for row in rows
        ]

    def fetch_candidate_items(self, db: Session) -> tuple[list[CandidateItem], bool]:
        now = datetime.utcnow()
        rows = (
            db.query(PlayerInjuryStatus)
            .filter(PlayerInjuryStatus.status != "healthy")
            .all()
        )
        items = [
            CandidateItem(
                tier=SourceTier.OFFICIAL,
                source_label="NBA injury status",
                item_ts=now,
                text=_injury_text(row.status, row.injury_type),
                player_name=row.player_name,
            )
            for row in rows
        ]
        return items, True

    def apply_signals(self, db: Session, game_date: date) -> dict:
        return apply_signals_to_nba_slate(db, game_date=game_date)
