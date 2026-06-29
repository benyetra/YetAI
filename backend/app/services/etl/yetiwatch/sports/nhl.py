"""NHL YetiWatch adapter — expected goalie starters on today's slate."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.predictions_models import NHLGoalie
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nhl.confirm_starters import build_slate_starter_context
from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.yetiwatch.slate import SlateSubject


def _games_for_date(game_date: date) -> list[dict]:
    client = NHLAPIClient()
    schedule = client.get_schedule(game_date.strftime("%Y-%m-%d"))
    if not schedule or "gameWeek" not in schedule:
        return []
    games: list[dict] = []
    date_key = game_date.strftime("%Y-%m-%d")
    for game_day in schedule["gameWeek"]:
        if game_day.get("date") == date_key:
            games.extend(game_day.get("games", []))
    return games


class NHLAdapter:
    sport = "nhl"

    def game_date(self) -> date:
        return now_eastern().date()

    def load_slate(self, db: Session, game_date: date) -> list[SlateSubject]:
        client = NHLAPIClient()
        games = _games_for_date(game_date)
        summary = build_slate_starter_context(games, client)
        subjects: list[SlateSubject] = []
        for slot in summary.slots:
            if not slot.goalie_id:
                continue
            subjects.append(
                SlateSubject(
                    sport=self.sport,
                    entity_id=str(slot.goalie_id),
                    entity_name=slot.goalie_name or "Unknown",
                    team_id=str(slot.team_id),
                    opponent_id=str(slot.opponent_team_id),
                    game_date=game_date,
                    home_game=slot.is_home,
                )
            )
        return subjects

    def fetch_candidate_items(self, db: Session) -> tuple[list[CandidateItem], bool]:
        now = datetime.utcnow()
        rows = (
            db.query(NHLGoalie)
            .filter(
                NHLGoalie.injury_status.isnot(None),
                NHLGoalie.injury_status.notin_(["healthy", "Healthy"]),
            )
            .all()
        )
        items = [
            CandidateItem(
                tier=SourceTier.OFFICIAL,
                source_label="NHL goalie injury status",
                item_ts=now,
                text=f"{row.injury_status} ({row.injury_description or ''})".strip(),
                player_name=row.name,
                team_name=row.team_name,
            )
            for row in rows
        ]
        return items, True

    def apply_signals(self, db: Session, game_date: date) -> dict:
        return {"status": "ok", "adjusted": 0, "reason": "nhl_no_minutes_apply"}
