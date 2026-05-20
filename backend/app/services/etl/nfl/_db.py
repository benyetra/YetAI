"""SQLAlchemy session bridge for ported YetiBets NFL scripts."""

from __future__ import annotations

from typing import Any

from app.core.database import SessionLocal

_session = None


def init_session():
    global _session
    if _session is None:
        _session = SessionLocal()
    return _session


def close_session():
    global _session
    if _session is not None:
        _session.close()
        _session = None


class _SessionProxy:
    def query(self, *args: Any, **kwargs: Any):
        return init_session().query(*args, **kwargs)

    def add(self, obj: Any) -> None:
        init_session().add(obj)

    def commit(self) -> None:
        init_session().commit()

    def rollback(self) -> None:
        init_session().rollback()

    def delete(self, obj: Any) -> None:
        init_session().delete(obj)

    def bulk_save_objects(self, objects: list) -> None:
        init_session().bulk_save_objects(objects)

    def remove(self) -> None:
        close_session()

    def execute(self, statement, *args, **kwargs):
        return init_session().execute(statement, *args, **kwargs)

    def flush(self) -> None:
        init_session().flush()


db_session = _SessionProxy()
