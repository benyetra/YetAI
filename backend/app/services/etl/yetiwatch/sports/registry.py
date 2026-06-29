"""Sport adapter registry for YetiWatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from app.services.etl.yetiwatch.ingest import CandidateItem
from app.services.etl.yetiwatch.slate import SlateSubject


class SportAdapter(Protocol):
    sport: str

    def game_date(self) -> date: ...

    def load_slate(self, db: Session, game_date: date) -> list[SlateSubject]: ...

    def fetch_candidate_items(
        self, db: Session
    ) -> tuple[list[CandidateItem], bool]: ...

    def apply_signals(self, db: Session, game_date: date) -> dict: ...


@dataclass(frozen=True)
class _AdapterRef:
    module: str
    class_name: str


_ADAPTERS: dict[str, _AdapterRef] = {
    "nba": _AdapterRef("app.services.etl.yetiwatch.sports.nba", "NBAAdapter"),
    "wnba": _AdapterRef("app.services.etl.yetiwatch.sports.wnba", "WNBAAdapter"),
    "mlb": _AdapterRef("app.services.etl.yetiwatch.sports.mlb", "MLBAdapter"),
    "nfl": _AdapterRef("app.services.etl.yetiwatch.sports.nfl", "NFLAdapter"),
    "nhl": _AdapterRef("app.services.etl.yetiwatch.sports.nhl", "NHLAdapter"),
}

SUPPORTED_SPORTS = tuple(_ADAPTERS.keys())


def get_adapter(sport: str) -> SportAdapter:
    key = sport.lower()
    ref = _ADAPTERS.get(key)
    if not ref:
        raise ValueError(f"Unsupported YetiWatch sport: {sport}")
    import importlib

    mod = importlib.import_module(ref.module)
    cls = getattr(mod, ref.class_name)
    return cls()
