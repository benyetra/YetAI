"""The three 2026-11-18 migrations form one line off 20261115_fair_price_shadow and run
up and down on sqlite against the real table shapes (Postgres runs the IF EXISTS paths)."""

import importlib.util
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

import app.models.predictions_models as pm
from app.core.database import Base

BACKEND = Path(__file__).resolve().parents[1]
CHAIN = (
    "20261118_prop_best_fair_ev",
    "20261118_nba_prop_low_sample",
    "20261118_nhl_goalie_uq",
)
NEW_COLUMNS = {"best_fair_prob", "best_ev", "best_quoted_at", "low_sample"}


def _load(rev):
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    return script, script.get_revision(rev)


def test_one_head_and_the_chain_order():
    script, _ = _load(CHAIN[-1])
    assert script.get_heads() == [CHAIN[-1]]
    downs = [script.get_revision(r).down_revision for r in CHAIN]
    assert downs == ["20261115_fair_price_shadow", *CHAIN[:-1]]


def _module(rev):
    _, r = _load(rev)
    spec = importlib.util.spec_from_file_location(rev, r.path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_chain_upgrades_and_downgrades_on_sqlite():
    mods = [_module(r) for r in CHAIN]
    tables = set(mods[0].PROP_TABLES) | set(mods[1].TABLES) | {mods[2].TABLE}
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        # Real shapes minus the columns these migrations add, as before the deploy.
        for t in Base.metadata.sorted_tables:
            if t.name in tables:
                cols = [c.copy() for c in t.columns if c.name not in NEW_COLUMNS]
                sa.Table(t.name, sa.MetaData(), *cols).create(conn)
        goalie = pm.NHLGoaliePredictions.__table__
        row = dict(
            game_date=date(2026, 11, 17),
            team_id=1,
            goalie_id=9,
            goalie_name="g",
            team_name="t",
            opponent_team_name="o",
            opponent_team_id=2,
            predicted_saves=25.0,
            predicted_shots_against=27.0,
            predicted_save_pct=0.9,
        )
        for i, scratch in ((1, None), (2, None), (3, True)):  # two live dups + scratch
            conn.execute(goalie.insert().values(id=i, was_scratch=scratch, **row))
        ops = Operations(MigrationContext.configure(conn))
        with Operations.context(ops.migration_context):
            for m in mods:
                m.upgrade()
        for t in mods[0].PROP_TABLES:
            assert {"best_fair_prob", "best_ev", "best_quoted_at"} <= _cols(conn, t)
        for t in mods[1].TABLES:
            assert "low_sample" in _cols(conn, t)
        ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM " + goalie.name))]
        assert sorted(ids) == [2, 3]  # newest live row kept, scratch row kept
        with Operations.context(ops.migration_context):
            for m in reversed(mods):
                m.downgrade()
        for t in tables:
            assert not NEW_COLUMNS & _cols(conn, t)
        names = {i["name"] for i in sa.inspect(conn).get_indexes(goalie.name)}
        assert mods[2].INDEX not in names
