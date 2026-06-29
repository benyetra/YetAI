"""NFL YetiWatch adapter — starting QBs for the current week."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
from app.services.etl.nba._espn import now_eastern
from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.yetiwatch.slate import SlateSubject


class NFLAdapter:
    sport = "nfl"

    def game_date(self) -> date:
        return now_eastern().date()

    def _week_context(self) -> tuple[int, int]:
        season = get_nfl_season()
        week = get_current_nfl_week(season)
        return season, week

    def load_slate(self, db: Session, game_date: date) -> list[SlateSubject]:
        from app.services.etl.nfl.qb_dynamic import get_dynamic_starting_qbs

        season, week = self._week_context()
        qbs = get_dynamic_starting_qbs(season, week)
        subjects: list[SlateSubject] = []
        for qb in qbs:
            entity_id = qb.get("player_id") or qb.get("gsis_id")
            if not entity_id:
                continue
            subjects.append(
                SlateSubject(
                    sport=self.sport,
                    entity_id=str(entity_id),
                    entity_name=qb.get("name") or "Unknown",
                    team_id=str(qb.get("team_id")) if qb.get("team_id") else None,
                    opponent_id=None,
                    game_date=game_date,
                )
            )
        return subjects

    def fetch_candidate_items(self, db: Session) -> tuple[list[CandidateItem], bool]:
        from app.services.etl.nfl.qb_dynamic import get_dynamic_starting_qbs

        season, week = self._week_context()
        qbs = get_dynamic_starting_qbs(season, week)
        now = datetime.utcnow()
        items: list[CandidateItem] = []
        for qb in qbs:
            status = qb.get("injury_status") or "Healthy"
            if str(status).lower() in {"healthy", "active"}:
                continue
            name = qb.get("name")
            if not name:
                continue
            items.append(
                CandidateItem(
                    tier=SourceTier.OFFICIAL,
                    source_label="NFL injury report",
                    item_ts=now,
                    text=str(status),
                    player_name=name,
                    team_name=qb.get("team_name"),
                )
            )
        return items, True

    def apply_signals(self, db: Session, game_date: date) -> dict:
        return {"status": "ok", "adjusted": 0, "reason": "nfl_no_minutes_apply"}
