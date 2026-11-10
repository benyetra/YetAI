"""Remove a projection that should no longer be on today's board."""

from __future__ import annotations

from datetime import date


def drop_projection_for_today(db, model, today: date, player_id: int) -> bool:
    """Delete ``player_id``'s row for ``today`` from a projection table.

    The overnight run projects everyone not yet ruled out. When a later
    refresh finds the player out, skipping him is not enough: the morning row,
    with its line and pick, would stay on the board (and in front of the
    auto-picker) all day.
    """
    deleted = (
        db.query(model)
        .filter(model.date == today, model.player_id == player_id)
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
    return bool(deleted)
