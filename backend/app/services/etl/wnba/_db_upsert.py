"""Postgres upsert helpers for WNBA ETL.

SQLAlchemy ``merge()`` without a loaded primary key always INSERTs. These helpers
use ``INSERT ... ON CONFLICT DO UPDATE`` against natural keys / unique constraints.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


def upsert_many(
    session: Session,
    model: type,
    rows: Sequence[dict[str, Any]],
    *,
    conflict_keys: Sequence[str],
    update_keys: Sequence[str] | None = None,
) -> int:
    """Insert rows, updating columns on conflict. Returns number of rows in batch."""
    if not rows:
        return 0

    table = model.__table__
    if update_keys is None:
        skip = set(conflict_keys) | {"id"}
        update_keys = [key for key in rows[0] if key not in skip]

    stmt = insert(table).values(list(rows))
    if not update_keys:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(conflict_keys))
    else:
        excluded = stmt.excluded
        set_ = {key: getattr(excluded, key) for key in update_keys}
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_keys),
            set_=set_,
        )
    session.execute(stmt)
    return len(rows)
