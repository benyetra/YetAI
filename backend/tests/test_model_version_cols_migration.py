"""C5: the model_version migration fails fast on locks and is re-runnable."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261113_model_version_cols.py"
)


def _mig(tables):
    spec = importlib.util.spec_from_file_location("mv_cols_mig", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.TABLES = tables
    return mod


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_sqlite_upgrade_adds_columns_and_is_rerunnable():
    engine = sa.create_engine("sqlite://")
    mig = _mig(["t1", "t2"])
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE t1 (id INTEGER)"))
        # t2 already has the column (a partial earlier run)
        conn.execute(sa.text("CREATE TABLE t2 (id INTEGER, model_version VARCHAR(20))"))
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()  # second run must not raise
        assert "model_version" in _cols(conn, "t1")
        assert "model_version" in _cols(conn, "t2")


def test_postgres_upgrade_sets_lock_timeout_first_and_uses_if_not_exists(monkeypatch):
    mig = _mig(["t1", "t2"])
    stmts = []
    fake_op = MagicMock()
    fake_op.get_bind.return_value.dialect.name = "postgresql"
    fake_op.execute.side_effect = lambda sql: stmts.append(str(sql))
    monkeypatch.setattr(mig, "op", fake_op)
    mig.upgrade()
    assert stmts[0] == "SET LOCAL lock_timeout = '5s'"
    assert all("IF NOT EXISTS" in s for s in stmts[1:])
    assert len(stmts) == 3
