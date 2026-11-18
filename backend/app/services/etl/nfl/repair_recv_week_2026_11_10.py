"""One-off repair: the 26 ``recv_nonml_v1`` receiving-yards rows of 2026-11-10.

Those rows were written on Tuesday 11-10 by code that had no schedule filter,
so they carry the calendar week (9) and ``game_date`` = the run date, but the
lines on them were week-10 lines. The grader then scored them against week-9
games played before the line existed (n=21, "MAE 15.21 vs line 21.50"), a
meaningless record.

Decision: DELETE, not relabel. A correct relabel needs each player's real
week-10 game date (not stored), the rows came from the first model that
over-projected by ~28 yards a player (superseded by v2 the same day), and a
relabel to week 10 can collide with the v2 board's unique key
(season, week, player_id). The v2 rows are the real week-10 board.

It deletes the v1 rows written that day (the whole of 11-10 Eastern, as a UTC
window: created_at is stored in UTC), and any ``pred_recv_yds_actuals`` row
graded from them (same season, week and player_id as a deleted v1 row), unless
a non-v1 prediction shares that key: that actual belongs to the v2 row.

Dry run by default (prints what it would delete, changes nothing):

    cd backend && python -m app.services.etl.nfl.repair_recv_week_2026_11_10

Write the change:

    cd backend && python -m app.services.etl.nfl.repair_recv_week_2026_11_10 --apply
"""

from __future__ import annotations

import sys
from datetime import datetime

MODEL_VERSION = "recv_nonml_v1"
# All of 2026-11-10 Eastern (EST, UTC-5) in UTC: rows written after 19:00 ET
# carry the next UTC day.
WINDOW_START_UTC = datetime(2026, 11, 10, 5)
WINDOW_END_UTC = datetime(2026, 11, 11, 5)


def repair(session, *, apply: bool = False) -> dict:
    """Return counts (and delete when ``apply``); the caller commits."""
    from app.models.predictions_models import RecvYdsActuals, RecvYdsPredictions

    preds = (
        session.query(RecvYdsPredictions)
        .filter(
            RecvYdsPredictions.model_version == MODEL_VERSION,
            RecvYdsPredictions.created_at >= WINDOW_START_UTC,
            RecvYdsPredictions.created_at < WINDOW_END_UTC,
        )
        .all()
    )
    actuals = []
    for pred in preds:
        shared = (
            session.query(RecvYdsPredictions)
            .filter(
                RecvYdsPredictions.season == pred.season,
                RecvYdsPredictions.week == pred.week,
                RecvYdsPredictions.player_id == pred.player_id,
                RecvYdsPredictions.model_version != MODEL_VERSION,
            )
            .first()
        )
        if shared is not None:
            continue  # a v2 row owns this key's actual
        actuals.extend(
            session.query(RecvYdsActuals)
            .filter_by(season=pred.season, week=pred.week, player_id=pred.player_id)
            .all()
        )
    result = {"predictions": len(preds), "actuals": len(actuals), "applied": apply}
    for pred in preds:
        print(
            f"{'DELETE' if apply else 'would delete'} pred {pred.season} "
            f"wk{pred.week} {pred.player_name} ({pred.player_id})"
        )
    for act in actuals:
        print(
            f"{'DELETE' if apply else 'would delete'} actual {act.season} "
            f"wk{act.week} {act.player_name} ({act.player_id})"
        )
    if apply:
        for row in actuals + preds:
            session.delete(row)
        session.flush()
    return result


def main(argv: list[str] | None = None) -> dict:
    from app.core.database import SessionLocal

    apply = "--apply" in (sys.argv[1:] if argv is None else argv)
    session = SessionLocal()
    try:
        result = repair(session, apply=apply)
        if apply:
            session.commit()
        else:
            print("dry run: pass --apply to delete")
        return result
    finally:
        session.close()


if __name__ == "__main__":
    main()
