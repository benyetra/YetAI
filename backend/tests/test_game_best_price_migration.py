"""Game best-price migration: chained after the goalie index, re-runnable, reversible."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20261118_game_best_price.py"
)
BEST = {
    "best_book",
    "best_line",
    "best_price",
    "best_side",
    "best_fair_prob",
    "best_ev",
    "best_quoted_at",
}
ML = {
    "ml_best_book",
    "ml_best_price",
    "ml_best_side",
    "ml_best_fair_prob",
    "ml_best_ev",
    "ml_best_quoted_at",
}


def _mig():
    spec = importlib.util.spec_from_file_location("game_best_mig", PATH)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


def _cols(conn, t):
    return {c["name"] for c in sa.inspect(conn).get_columns(t)}


def test_chain_and_tables_match_the_models():
    from app.models import predictions_models as m

    mig = _mig()
    assert mig.down_revision == "20261118_nhl_goalie_uq"
    by_table = {c.__tablename__: c for c in vars(m).values() if hasattr(c, "__table__")}
    for t in mig.TABLES:
        assert BEST <= set(by_table[t].__table__.columns.keys()), t
    for t in mig.ML_TABLES:
        assert ML <= set(by_table[t].__table__.columns.keys()), t


def test_sqlite_upgrade_is_rerunnable_and_downgrade_removes_columns():
    mig = _mig()
    mig.TABLES, mig.ML_TABLES = ["t1", "t2"], ["t1"]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE t1 (id INTEGER)"))
        conn.execute(sa.text("CREATE TABLE t2 (id INTEGER, best_ev FLOAT)"))
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()
        assert BEST | ML <= _cols(conn, "t1")
        assert BEST <= _cols(conn, "t2") and not ML & _cols(conn, "t2")
        with Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
        assert _cols(conn, "t1") == {"id"} and _cols(conn, "t2") == {"id"}
