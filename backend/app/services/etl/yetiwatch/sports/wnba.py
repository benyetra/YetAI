"""WNBA YetiWatch adapter."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBATodayActivePlayers
from app.services.etl.nba._espn import now_eastern
from app.services.etl.wnba._espn import fetch_injuries
from app.services.etl.yetiwatch.apply_signals import apply_signals_to_wnba_slate
from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.yetiwatch.slate import SlateSubject


def _injury_text(status: str, injury_type: str | None) -> str:
    parts = [status]
    if injury_type:
        parts.append(f"({injury_type})")
    return " ".join(parts)


class WNBAAdapter:
    sport = "wnba"

    def game_date(self) -> date:
        return now_eastern().date()

    def load_slate(self, db: Session, game_date: date) -> list[SlateSubject]:
        rows = (
            db.query(WNBATodayActivePlayers)
            .filter(WNBATodayActivePlayers.game_date == game_date)
            .all()
        )
        return [
            SlateSubject(
                sport=self.sport,
                entity_id=str(row.player_id),
                entity_name=row.player_name,
                team_id=str(row.team_id),
                opponent_id=(
                    str(row.opponent_team_id)
                    if row.opponent_team_id is not None
                    else None
                ),
                game_date=game_date,
                home_game=row.home_game,
            )
            for row in rows
        ]

    def fetch_candidate_items(self, db: Session) -> tuple[list[CandidateItem], bool]:
        rows, fetch_ok = fetch_injuries()
        if not fetch_ok:
            return [], False
        now = datetime.utcnow()
        items = [
            CandidateItem(
                tier=SourceTier.OFFICIAL,
                source_label="ESPN WNBA injuries",
                item_ts=now,
                text=_injury_text(row.get("status") or "Out", row.get("injury_type")),
                player_name=(row.get("player_name") or "").strip() or None,
                team_name=row.get("team_name"),
            )
            for row in rows
            if (row.get("player_name") or "").strip()
        ]
        return items, True

    def apply_signals(self, db: Session, game_date: date) -> dict:
        return apply_signals_to_wnba_slate(db, game_date=game_date)
