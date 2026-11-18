"""best_fair_prob / best_ev migration is re-runnable on sqlite and reversible."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261118_prop_best_fair_ev.py"
)


def test_sqlite_upgrade_adds_columns_and_is_rerunnable():
    spec = importlib.util.spec_from_file_location("fair_ev_mig", PATH)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    mig.PROP_TABLES = ["t1", "t2"]
    assert mig.down_revision == "20261115_fair_price_shadow"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE t1 (id INTEGER)"))
        conn.execute(sa.text("CREATE TABLE t2 (id INTEGER, best_ev FLOAT)"))
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()
        for t in ("t1", "t2"):
            have = {c["name"] for c in sa.inspect(conn).get_columns(t)}
            assert {"best_fair_prob", "best_ev", "best_quoted_at"} <= have
        with Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
        for t in ("t1", "t2"):
            have = {c["name"] for c in sa.inspect(conn).get_columns(t)}
            assert not {"best_fair_prob", "best_ev", "best_quoted_at"} & have
