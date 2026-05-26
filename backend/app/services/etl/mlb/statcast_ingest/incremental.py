from __future__ import annotations

import logging
from datetime import date, timedelta

from app.services.etl.mlb.statcast_ingest.backfill import backfill_month

logger = logging.getLogger(__name__)


def statcast_incremental(day: date | None = None, force: bool = True) -> dict:
    """Refresh the current month's partition (yesterday's games included)."""
    target = day or (date.today() - timedelta(days=1))
    season, month = target.year, target.month
    uri = backfill_month(season, month, force=force)
    return {"season": season, "month": month, "uri": uri, "as_of": target.isoformat()}
