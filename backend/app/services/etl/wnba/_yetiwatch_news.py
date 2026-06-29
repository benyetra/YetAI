"""Attach YetiWatch news_string to WNBA prop projection rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.services.etl.yetiwatch.apply_signals import news_for_entity


def attach_yetiwatch_news(
    row: dict,
    *,
    db: Session,
    player_id: int,
    game_date: date,
) -> None:
    news = news_for_entity(db, sport="wnba", entity_id=player_id, game_date=game_date)
    if news:
        row["news"] = news
