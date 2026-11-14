"""Leakage and derivation tests for the NBA line-residual dataset (pure pandas + SQLite)."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app.services.etl.nba.residual import dataset as ds
from app.services.etl.nba.residual.dataset import (
    FEATURE_FAMILIES,
    TARGETS,
    build_rows,
    feature_columns,
    load_inputs,
    serve_rows,
)

H, A = 1, 2  # team ids; players 1-6 are team H, 11-16 team A
START = pd.Timestamp("2026-01-01")
N_GAMES = 16


def _fixture(n_games=N_GAMES, sit_out=None, dnp=None, line_zero=None):
    """H hosts A every other day. `sit_out` = {(player, game_index)} with no box row."""
    sit_out, dnp = sit_out or set(), dnp or set()
    box, finals, glines, lines = [], [], [], []
    rng = np.random.default_rng(0)
    for g in range(n_games):
        d = START + pd.Timedelta(days=2 * g)
        home = g % 2 == 0
        h_id, a_id = (H, A) if home else (A, H)
        finals.append((d, h_id, a_id, 100 + g, 98 + g))
        glines.append((d, h_id, a_id, -3.5 if home else 3.5, 215.0 + g))
        for team, base in ((H, 1), (A, 11)):
            opp = A if team == H else H
            for k in range(6):
                pid = base + k
                if (pid, g) in sit_out:
                    continue
                mins = 0.0 if (pid, g) in dnp else (34.0 - 3 * k)
                box.append(
                    (
                        pid,
                        d,
                        opp,
                        mins,
                        float(rng.integers(2, 12)),
                        float(rng.integers(1, 9)),
                        team == h_id,
                    )
                )
                lines.append(("rebounds", pid, d, 5.5 + (k % 3), "fanduel_projection"))
    box = pd.DataFrame(
        box,
        columns=[
            "player_id",
            "date",
            "opponent_team_id",
            "minutes",
            "rebounds",
            "assists",
            "home_game",
        ],
    )
    finals = pd.DataFrame(
        finals, columns=["date", "home_id", "away_id", "home_score", "away_score"]
    )
    glines = pd.DataFrame(
        glines, columns=["date", "home_id", "away_id", "spread_home", "total"]
    )
    lines = pd.DataFrame(
        lines, columns=["stat", "player_id", "date", "line", "line_source"]
    )
    for c in ("over_price", "under_price", "close_line"):
        lines[c] = np.nan
    lines["price_side"] = None
    return {"box": box, "lines": lines, "finals": finals, "game_lines": glines}


def _truncate(inputs, cutoff):
    return {k: v[v["date"] <= cutoff].copy() for k, v in inputs.items()}


def assert_no_lookahead(build_fn, inputs, cutoff):
    """Features of rows dated <= cutoff must not change when later data is removed."""
    cutoff = pd.Timestamp(cutoff)
    full = build_fn(inputs)
    full = (
        full[full["date"] <= cutoff]
        .sort_values(["date", "player_id"])
        .reset_index(drop=True)
    )
    trunc = (
        build_fn(_truncate(inputs, cutoff))
        .sort_values(["date", "player_id"])
        .reset_index(drop=True)
    )
    assert len(full) == len(trunc) > 0
    cols = [c for c in full.columns if c not in TARGETS]
    pd.testing.assert_frame_equal(full[cols], trunc[cols], check_dtype=False)


def test_no_lookahead_passes_and_leaky_variant_fails():
    inputs = _fixture(sit_out={(1, 9)})
    cutoff = START + pd.Timedelta(days=20)
    assert_no_lookahead(lambda i: build_rows(i, "rebounds"), inputs, cutoff)

    def leaky(i):
        out = build_rows(i, "rebounds")
        out["form_leak"] = out.groupby("player_id")["actual"].shift(
            -1
        )  # next game's actual
        return out

    with pytest.raises(AssertionError):
        assert_no_lookahead(leaky, inputs, cutoff)


def test_teammate_out_counted_and_team_derived():
    inputs = _fixture(sit_out={(1, 12)})  # H's top-minutes regular misses game 12
    rows = build_rows(inputs, "rebounds")
    day = START + pd.Timedelta(days=24)
    r = rows[(rows.date == day) & (rows.player_id == 2)].iloc[0]
    assert r.team_id == H and r.opponent_team_id == A
    assert r.team_n_out == 1
    assert r.team_out_minutes == pytest.approx(34.0)
    prior = rows[
        (rows.date == START + pd.Timedelta(days=22)) & (rows.player_id == 2)
    ].iloc[0]
    assert prior.team_n_out == 0 and prior.team_with_without == 0
    # opponent player sees no one out
    assert rows[(rows.date == day) & (rows.player_id == 11)].iloc[0].team_n_out == 0


def test_push_dnp_and_placeholder():
    inputs = _fixture(dnp={(3, 10)})
    box = inputs["box"]
    mask = (box.player_id == 2) & (box.date == START + pd.Timedelta(days=14))
    inputs["lines"].loc[
        (inputs["lines"].player_id == 2)
        & (inputs["lines"].date == START + pd.Timedelta(days=14)),
        "line",
    ] = float(box[mask].rebounds.iloc[0])
    rows = build_rows(inputs, "rebounds")
    push = rows[
        (rows.player_id == 2) & (rows.date == START + pd.Timedelta(days=14))
    ].iloc[0]
    assert push.resid == 0 and np.isnan(push.over)
    assert rows[
        (rows.player_id == 3) & (rows.date == START + pd.Timedelta(days=20))
    ].empty
    assert set(rows["over"].dropna()) <= {0.0, 1.0}


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        for sql in (
            "CREATE TABLE pred_recent_games (player_id int, game_date date, opponent_team_id int, "
            "minutes float, rebounds float, assists float, points float, offensive_rebounds float, "
            "defensive_rebounds float, home_game bool)",
            "CREATE TABLE pred_rebounds_projections (id integer primary key, date date, player_id int, "
            "fanduel_line float, fanduel_price int, fanduel_over_under varchar)",
            "CREATE TABLE pred_assists_projections (id integer primary key, date date, player_id int, "
            "fanduel_line float, fanduel_price int, fanduel_over_under varchar)",
            "CREATE TABLE pred_team_offense_stats (team_id int, team_name varchar)",
            "CREATE TABLE pred_nba_spread_actuals (game_date date, home_team_name varchar, "
            "away_team_name varchar, home_score int, away_score int)",
            "CREATE TABLE pred_nba_game_lines (game_date date, home_team_id int, away_team_id int, "
            "home_team_name varchar, away_team_name varchar, spread_home float, total float)",
        ):
            c.execute(text(sql))
        c.execute(
            text(
                "INSERT INTO pred_team_offense_stats VALUES (1,'LA Clippers'),(2,'Boston Celtics')"
            )
        )
        c.execute(
            text(
                "INSERT INTO pred_nba_spread_actuals VALUES ('2026-01-05','Los Angeles Clippers',"
                "'Boston Celtics',100,90)"
            )
        )
        c.execute(
            text(
                "INSERT INTO pred_nba_game_lines VALUES ('2026-01-05',NULL,NULL,'Los Angeles Clippers',"
                "'Boston Celtics',-4.5,210)"
            )
        )
        c.execute(
            text(
                "INSERT INTO pred_recent_games VALUES (7,'2026-01-05',2,30,8,3,10,2,6,1),"
                "(8,'2026-01-05',1,28,5,6,10,1,4,0)"
            )
        )
        c.execute(
            text(
                "INSERT INTO pred_rebounds_projections VALUES "
                "(1,'2026-01-05',7,0.0,NULL,NULL),(2,'2026-01-05',7,7.5,-120,'Over'),"
                "(3,'2026-01-05',7,8.5,110,'Over'),(4,'2026-01-05',8,5.5,-105,'Under')"
            )
        )
    return eng


def test_load_inputs_line_rules_and_team_names(engine):
    with engine.connect() as c:
        inp = load_inputs(c, "2026-01-05", "2026-01-05")
    ln = inp["lines"]
    ln = ln[ln.stat == "rebounds"].set_index("player_id")
    assert ln.loc[7, "line"] == 8.5  # latest id wins, 0.0 placeholder ignored
    assert ln.loc[7, "over_price"] == 110 and np.isnan(ln.loc[7, "under_price"])
    assert ln.loc[8, "under_price"] == -105 and ln.loc[8, "price_side"] == "under"
    assert inp["finals"].home_id.iloc[0] == 1 and inp["game_lines"].home_id.iloc[0] == 1
    rows = build_rows(inp, "rebounds")
    assert set(rows.team_id) == {1, 2}  # player 7 faced team 2 -> on team 1


def test_snapshot_table_preferred_when_present_else_fallback(engine):
    with engine.connect() as c:
        assert (
            load_inputs(c, "2026-01-05", "2026-01-05")["lines"].line_source
            == "fanduel_projection"
        ).all()
    with engine.begin() as c:
        c.execute(
            text(
                f"CREATE TABLE {ds.ODDS_SNAPSHOT_TABLE} (game_date date, stat varchar, player_id int, "
                "line float, over_price int, under_price int, snapshot_at timestamp, "
                "game_start timestamp, is_closing bool)"
            )
        )
        c.execute(
            text(
                f"INSERT INTO {ds.ODDS_SNAPSHOT_TABLE} VALUES "
                "('2026-01-05','rebounds',7,9.5,-110,-110,'2026-01-05 15:00','2026-01-05 20:00',0),"
                "('2026-01-05','rebounds',7,10.5,-115,-105,'2026-01-05 19:30','2026-01-05 20:00',1),"
                "('2026-01-05','rebounds',7,4.5,-110,-110,'2026-01-05 21:00','2026-01-05 20:00',0)"
            )
        )
    with engine.connect() as c:
        ln = load_inputs(c, "2026-01-05", "2026-01-05")["lines"]
    ln = ln[ln.stat == "rebounds"].set_index("player_id")
    assert (
        ln.loc[7, "line_source"] == "snapshot" and ln.loc[7, "line"] == 9.5
    )  # post-game dropped
    assert ln.loc[7, "close_line"] == 10.5 and ln.loc[7, "under_price"] == -110
    assert ln.loc[8, "line_source"] == "fanduel_projection"  # no snapshot -> fallback


def test_serve_rows_match_build_rows_for_same_slot():
    inputs = _fixture(sit_out={(1, 12)})
    day = START + pd.Timedelta(days=24)
    built = build_rows(inputs, "rebounds")
    built = built[built.date == day].set_index("player_id")
    hist = {k: v[v["date"] < day].copy() for k, v in inputs.items()}
    hist["lines"] = inputs["lines"][inputs["lines"]["date"] <= day].copy()
    hist["game_lines"] = inputs["game_lines"][
        inputs["game_lines"]["date"] <= day
    ].copy()
    played = inputs["box"][inputs["box"].date == day]
    home = day in set(inputs["finals"].loc[inputs["finals"].home_id == H, "date"])
    active = pd.DataFrame(
        {
            "player_id": played.player_id,
            "team_id": np.where(played.player_id < 10, H, A),
            "opponent_team_id": played.opponent_team_id,
            "is_home_game": played.home_game,
        }
    )
    served = serve_rows(hist, "rebounds", day, active, out_player_ids=[]).set_index(
        "player_id"
    )
    assert len(served) == len(built) and home in (True, False)
    cols = feature_columns()
    pd.testing.assert_frame_equal(
        served[cols].sort_index(), built[cols].sort_index(), check_dtype=False
    )
    # an injured-out regular (still listed active) counts as out
    served2 = serve_rows(hist, "rebounds", day, active, out_player_ids=[2]).set_index(
        "player_id"
    )
    assert served2.loc[3, "team_n_out"] == built.loc[3, "team_n_out"] + 1


def test_feature_families_prefixed():
    for prefix, cols in FEATURE_FAMILIES.items():
        assert all(c.startswith(prefix) for c in cols)
    assert len(feature_columns()) == len(set(feature_columns()))
