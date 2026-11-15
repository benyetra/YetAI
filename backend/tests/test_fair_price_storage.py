"""fair_price_shadow_flags / fair_price_weights migration and models (SQLite)."""

import importlib.util
import pathlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.models.predictions_models import FairPriceShadowFlag, FairPriceWeights

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _load_migration():
    path = next(
        (APP.parent / "alembic" / "versions").glob("20261115_fair_price_shadow.py")
    )
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_creates_tables_twice_and_downgrades():
    mig = _load_migration()
    assert mig.revision == "20261115_fair_price_shadow" and len(mig.revision) <= 32
    assert mig.down_revision == "20261114_nba_prop_shadow"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()
            for table, model in (
                (mig.FLAGS, FairPriceShadowFlag),
                (mig.WEIGHTS, FairPriceWeights),
            ):
                cols = {c["name"] for c in inspect(conn).get_columns(table)}
                assert cols == {c.name for c in model.__table__.columns}
            mig.downgrade()
            names = inspect(conn).get_table_names()
            assert mig.FLAGS not in names and mig.WEIGHTS not in names
