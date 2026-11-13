"""Shared fixtures for auto-pick tests: an in-memory SQLite session.

Usage: ``def test_x(sqlite_db): ...``. Every table in ``Base.metadata`` is created
(JSONB columns are rendered as JSON on SQLite).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models.database_models  # noqa: F401  (register tables)
import app.models.predictions_models  # noqa: F401
from app.core.database import Base


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def sqlite_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
