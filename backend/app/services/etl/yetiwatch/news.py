"""Attach YetiWatch news strings to API projection rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import YetiWatchSignal


def load_news_map(
    db: Session,
    *,
    sport: str,
    game_date: date,
    entity_ids: list[str],
) -> dict[str, str]:
    if not entity_ids:
        return {}
    rows = (
        db.query(YetiWatchSignal)
        .filter(
            YetiWatchSignal.sport == sport,
            YetiWatchSignal.game_date == game_date,
            YetiWatchSignal.entity_id.in_(entity_ids),
        )
        .all()
    )
    return {row.entity_id: row.news_string for row in rows}


def _row_game_date(row: dict, date_key: str) -> date | None:
    raw_date = row.get(date_key) or row.get("game_date")
    if raw_date is None:
        return None
    if hasattr(raw_date, "date"):
        return raw_date.date()
    if isinstance(raw_date, str):
        return date.fromisoformat(raw_date[:10])
    return raw_date


def attach_news_to_rows(
    db: Session | None,
    rows: list[dict],
    *,
    sport: str,
    entity_key: str,
    date_key: str = "date",
) -> list[dict]:
    if not db or not rows:
        return rows

    by_date: dict[date, list[int]] = {}
    for idx, row in enumerate(rows):
        d = _row_game_date(row, date_key)
        if d is None:
            continue
        by_date.setdefault(d, []).append(idx)

    news_by_index: dict[int, str] = {}
    for game_date, indices in by_date.items():
        ids = [
            str(rows[i].get(entity_key))
            for i in indices
            if rows[i].get(entity_key) is not None
        ]
        news_map = load_news_map(db, sport=sport, game_date=game_date, entity_ids=ids)
        for i in indices:
            entity_id = rows[i].get(entity_key)
            if entity_id is None:
                continue
            news = news_map.get(str(entity_id))
            if news:
                news_by_index[i] = news

    out: list[dict] = []
    for idx, row in enumerate(rows):
        if idx in news_by_index:
            row = dict(row)
            row["news"] = news_by_index[idx]
        out.append(row)
    return out
