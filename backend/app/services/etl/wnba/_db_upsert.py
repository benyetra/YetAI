"""Postgres upsert helpers for WNBA ETL.

SQLAlchemy ``merge()`` without a loaded primary key always INSERTs. These helpers
use ``INSERT ... ON CONFLICT DO UPDATE`` against natural keys / unique constraints.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


def _normalize_row_keys(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every row has the same keys (None fill) for multiparam INSERT."""
    if not rows:
        return []
    all_keys: set[str] = set()
    for row in rows:
        all_keys.update(row.keys())
    return [{key: row.get(key) for key in all_keys} for row in rows]


def _dedupe_rows(
    rows: Sequence[dict[str, Any]],
    *,
    conflict_keys: Sequence[str],
) -> list[dict[str, Any]]:
    """Keep one row per conflict key tuple (last wins). Postgres rejects duplicate
    conflict targets within a single INSERT ... ON CONFLICT batch."""
    if not conflict_keys:
        return list(rows)
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in conflict_keys)
        deduped[key] = row
    return list(deduped.values())


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

    normalized = _normalize_row_keys(_dedupe_rows(rows, conflict_keys=conflict_keys))
    table = model.__table__
    if update_keys is None:
        skip = set(conflict_keys) | {"id"}
        update_keys = [key for key in normalized[0] if key not in skip]

    stmt = insert(table).values(normalized)
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
    return len(normalized)


def replace_matching(
    session: Session,
    model: type,
    rows: Sequence[dict[str, Any]],
    *,
    match_keys: Sequence[str],
) -> int:
    """Delete rows matching keys, then insert fresh rows (for tables without a unique index)."""
    if not rows:
        return 0
    table = model.__table__
    for row in rows:
        filters = {key: row[key] for key in match_keys}
        session.query(model).filter_by(**filters).delete()
    session.execute(insert(table).values(list(rows)))
    return len(rows)
