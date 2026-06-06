"""Historical WNBA game lines via The Odds API → pred_wnba_game_lines."""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAGameLines,
    WNBAGameLinesFetchLog,
    WNBASpreadActuals,
)
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._game_lines_odds import game_line_rows_from_events

logger = logging.getLogger(__name__)

SPORT = "basketball_wnba"
HISTORICAL_ODDS_URL = (
    "https://api.the-odds-api.com/v4/historical/sports/basketball_wnba/odds/"
)
# us region × h2h + spreads + totals ≈ 30 credits/date (Odds API pricing)
CREDITS_PER_DATE = 30


def resolve_odds_api_key() -> str | None:
    key = (os.getenv("ODDS_API_KEY") or os.getenv("ODDS_API") or "").strip()
    if key and key not in ("your_odds_api_key_here", "your-odds-api-key"):
        return key
    try:
        from app.core.config import settings

        key = (settings.ODDS_API_KEY or "").strip()
        if key and key not in ("your_odds_api_key_here", "your-odds-api-key"):
            return key
    except Exception:
        pass
    return None


def fetch_historical_events(
    game_date: date,
    *,
    api_key: str | None = None,
) -> list[dict] | None:
    """One Odds API historical call for all WNBA games on a calendar day."""
    key = api_key or resolve_odds_api_key()
    if not key:
        logger.warning("ODDS_API_KEY not set; skip historical WNBA game lines")
        return None

    from app.services.odds_api_sync import sync_odds_get

    resp = sync_odds_get(
        HISTORICAL_ODDS_URL,
        params={
            "apiKey": key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "date": f"{game_date.isoformat()}T17:00:00Z",
        },
        caller="etl.wnba.historical_game_lines",
        timeout=30,
        raise_for_status=False,
    )
    if resp is None:
        return None
    if resp.status_code != 200:
        logger.warning(
            "Historical WNBA odds %s: HTTP %s — %s",
            game_date,
            resp.status_code,
            (resp.text or "")[:200],
        )
        return None

    payload = resp.json()
    logger.info(
        "Historical WNBA odds %s: cost=%s remaining=%s",
        game_date,
        resp.headers.get("x-requests-last"),
        resp.headers.get("x-requests-remaining"),
    )
    if isinstance(payload, dict):
        data = payload.get("data")
        return data if isinstance(data, list) else None
    if isinstance(payload, list):
        return payload
    return None


def dates_with_spread_actuals(
    season_start: date,
    season_end: date,
) -> list[date]:
    db = SessionLocal()
    try:
        rows = (
            db.query(WNBASpreadActuals.game_date)
            .filter(WNBASpreadActuals.game_date >= season_start)
            .filter(WNBASpreadActuals.game_date <= season_end)
            .distinct()
            .order_by(WNBASpreadActuals.game_date.asc())
            .all()
        )
        return [row[0] for row in rows]
    finally:
        db.close()


def _line_exists_for_actual(
    db,
    game_date: date,
    home_team_name: str,
    away_team_name: str,
) -> bool:
    """Match lines stored on Eastern commence date (±1 day from actuals date)."""
    window_start = game_date - timedelta(days=1)
    window_end = game_date + timedelta(days=1)
    return (
        db.query(WNBAGameLines.id)
        .filter(WNBAGameLines.home_team_name == home_team_name)
        .filter(WNBAGameLines.away_team_name == away_team_name)
        .filter(WNBAGameLines.game_date >= window_start)
        .filter(WNBAGameLines.game_date <= window_end)
        .first()
        is not None
    )


def _spread_actuals_for_date(db, game_date: date) -> list[tuple[str, str]]:
    return (
        db.query(
            WNBASpreadActuals.home_team_name,
            WNBASpreadActuals.away_team_name,
        )
        .filter(WNBASpreadActuals.game_date == game_date)
        .all()
    )


def _fetch_date_is_logged(db, game_date: date) -> bool:
    return (
        db.query(WNBAGameLinesFetchLog.fetch_date)
        .filter(WNBAGameLinesFetchLog.fetch_date == game_date)
        .first()
        is not None
    )


def record_fetch_date(
    game_date: date,
    *,
    events_count: int,
    rows_written: int,
    source: str = "api",
) -> None:
    """Persist that the Odds API historical snapshot for this date was fetched."""
    db = SessionLocal()
    try:
        row = (
            db.query(WNBAGameLinesFetchLog)
            .filter(WNBAGameLinesFetchLog.fetch_date == game_date)
            .one_or_none()
        )
        if row is None:
            row = WNBAGameLinesFetchLog(
                fetch_date=game_date,
                events_count=events_count,
                rows_written=rows_written,
                source=source,
                fetched_at=datetime.utcnow(),
            )
            db.add(row)
        else:
            row.events_count = events_count
            row.rows_written = rows_written
            row.source = source
            row.fetched_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _should_skip_fetch_date(
    db,
    game_date: date,
    *,
    seed_partial: bool = True,
) -> bool:
    """Return True when no Odds API call is needed for this snapshot date."""
    if _fetch_date_is_logged(db, game_date):
        return True

    actuals = _spread_actuals_for_date(db, game_date)
    if not actuals:
        return True

    matched = sum(
        1
        for home, away in actuals
        if _line_exists_for_actual(db, game_date, home, away)
    )
    if matched == len(actuals):
        return True

    if seed_partial and matched > 0:
        record_fetch_date(
            game_date,
            events_count=0,
            rows_written=0,
            source="seed_partial",
        )
        logger.info(
            "seed fetch log for %s (%d/%d games had lines; skip re-fetch)",
            game_date,
            matched,
            len(actuals),
        )
        return True

    return False


def dates_missing_game_lines(
    dates: list[date],
) -> list[date]:
    if not dates:
        return []
    db = SessionLocal()
    try:
        missing: list[date] = []
        for game_date in dates:
            if not _should_skip_fetch_date(db, game_date):
                missing.append(game_date)
        return missing
    finally:
        db.close()


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    db = SessionLocal()
    try:
        count = upsert_many(
            db,
            WNBAGameLines,
            rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return count
    finally:
        db.close()


def backfill_dates(
    dates: list[date],
    *,
    dry_run: bool = False,
    skip_existing: bool = True,
    delay_seconds: float = 1.0,
    max_dates: int | None = None,
) -> dict:
    if skip_existing:
        target_dates = dates_missing_game_lines(dates)
        skipped = len(dates) - len(target_dates)
    else:
        target_dates = list(dates)
        skipped = 0

    if max_dates is not None:
        target_dates = target_dates[:max_dates]

    if dry_run:
        est_credits = len(target_dates) * CREDITS_PER_DATE
        return {
            "status": "dry_run",
            "dates_requested": len(dates),
            "dates_to_fetch": len(target_dates),
            "dates_skipped_existing": skipped,
            "estimated_credits": est_credits,
        }

    if not resolve_odds_api_key():
        return {"status": "error", "error": "ODDS_API_KEY not set"}

    fetched = 0
    rows_written = 0
    errors = 0
    for game_date in target_dates:
        events = fetch_historical_events(game_date)
        if events is None:
            errors += 1
            if delay_seconds:
                time.sleep(delay_seconds)
            continue
        rows = game_line_rows_from_events(events)
        row_count = upsert_rows(rows)
        rows_written += row_count
        record_fetch_date(
            game_date,
            events_count=len(events),
            rows_written=len(rows),
            source="api",
        )
        fetched += 1
        logger.info(
            "backfill %s: %d events → %d rows (running total rows=%d)",
            game_date,
            len(events),
            len(rows),
            rows_written,
        )
        if delay_seconds:
            time.sleep(delay_seconds)

    return {
        "status": "ok",
        "dates_requested": len(dates),
        "dates_skipped_existing": skipped,
        "dates_fetched": fetched,
        "rows_written": rows_written,
        "errors": errors,
    }


def backfill_from_actuals_window(
    season_start: date,
    season_end: date,
    *,
    max_dates: int | None = None,
    dry_run: bool = False,
    skip_existing: bool = True,
    delay_seconds: float = 1.0,
) -> dict:
    dates = dates_with_spread_actuals(season_start, season_end)
    result = backfill_dates(
        dates,
        dry_run=dry_run,
        skip_existing=skip_existing,
        delay_seconds=delay_seconds,
        max_dates=max_dates,
    )
    result["season_start"] = season_start.isoformat()
    result["season_end"] = season_end.isoformat()
    return result
