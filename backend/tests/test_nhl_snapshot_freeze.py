"""NHL snapshot freeze: started games are read-only, a failed run deletes nothing,
a pre-start scratch keeps the superseded goalie row flagged."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    NHLGoaliePredictions,
    NHLPlayer,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsPredictions,
)
from app.services.etl.nhl import daily_predictions as dp
from app.services.etl.nhl import generate_daily_predictions as gdp
from app.services.etl.nhl.confirm_starters import (
    GoalieStarterContext,
    SlateStarterSummary,
)

D = date(2026, 11, 13)
# 00:00Z Nov 14 = 7pm ET Nov 13: "after the start" below is past midnight UTC.
GAME = {
    "id": 1,
    "startTimeUTC": "2026-11-14T00:00:00Z",
    "homeTeam": {"id": 23, "abbrev": "VAN", "placeName": {"default": "Vancouver"}},
    "awayTeam": {"id": 3, "abbrev": "NYR", "placeName": {"default": "New York"}},
}
EVENTS = [
    {"id": "ev1", "away_team": "New York Rangers", "home_team": "Vancouver Canucks"}
]
BEFORE = datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(monkeypatch):
    eng = create_engine("sqlite://")
    for m in (
        NHLGoaliePredictions,
        NHLPlayer,
        NHLPlayerShotsPredictions,
        NHLTeamTotalsPredictions,
    ):
        m.__table__.create(eng)
    session = sessionmaker(bind=eng)()
    session.add(
        NHLPlayer(
            player_id=7,
            name="Q Player",
            team_id=23,
            team_name="Vancouver",
            position="C",
            shots_per_game=3.0,
            games_played=20,
        )
    )
    session.commit()
    monkeypatch.setattr(
        dp,
        "NHLAPIClient",
        lambda: SimpleNamespace(
            get_team_roster=lambda abbrev: {"forwards": [{"id": 7}]}
        ),
    )
    monkeypatch.setattr(dp, "db_session", session)
    state = {"now": BEFORE, "line": 2.5, "total": 5.5, "boom": False}
    monkeypatch.setattr(dp, "_now", lambda: state["now"])

    def pshots(**kw):
        if state["boom"]:
            raise RuntimeError("model down")
        return {"player_name": "Q Player", "predicted_shots": 3.2, "confidence": 60.0}

    monkeypatch.setattr(dp, "predict_player_shots", pshots)
    monkeypatch.setattr(
        dp,
        "enrich_player_shots_prediction_for_write",
        lambda pred, shots_line, extra_features: {
            "predicted_shots": 3.2,
            "model_version": "t",
            "features_used": {},
        },
    )
    monkeypatch.setattr(
        gdp,
        "get_player_shots_odds_for_event",
        lambda *a: (
            {} if state["line"] is None else {"Q Player": {"line": state["line"]}}
        ),
    )

    def ptotal(**kw):
        if state["boom"]:
            raise RuntimeError("model down")
        return {
            "predicted_home_goals": 3.0,
            "predicted_away_goals": 3.0,
            "suggested_ou_line": 5.5,
            "confidence": 60.0,
        }

    monkeypatch.setattr(dp, "predict_team_total_goals", ptotal)
    monkeypatch.setattr(
        dp,
        "enrich_team_totals_prediction_for_write",
        lambda pred, draftkings_ou_line, extra_features: {
            "predicted_total_goals": 6.0,
            "model_version": "t",
            "features_used": {},
        },
    )
    monkeypatch.setattr(
        gdp,
        "get_team_totals_odds_for_event",
        lambda *a: (
            {}
            if state["total"] is None
            else {"line": state["total"], "over_odds": -110, "under_odds": -110}
        ),
    )
    return SimpleNamespace(session=session, state=state)


def _players(env, games=(GAME,)):
    dp.generate_player_predictions(list(games), EVENTS)
    return env.session.query(NHLPlayerShotsPredictions).all()


def _totals(env, games=(GAME,)):
    dp.generate_team_totals_predictions(list(games), EVENTS)
    return env.session.query(NHLTeamTotalsPredictions).all()


def _snap(rows, *cols):
    return [(r.id, *(getattr(r, c) for c in cols)) for r in rows]


PCOLS = ("shots_line", "betting_recommendation", "predicted_shots")
TCOLS = ("draftkings_ou_line", "betting_recommendation", "edge", "over_odds")


# ---- player shots + team totals: same freeze contract ----
@pytest.mark.parametrize(
    "gen,cols,key",
    [(_players, PCOLS, "line"), (_totals, TCOLS, "total")],
    ids=["player_shots", "team_totals"],
)
class TestWriters:
    def test_started_game_is_frozen(self, env, gen, cols, key):
        first = _snap(gen(env), *cols)
        assert len(first) == 1 and first[0][1] is not None
        env.state["now"] = AFTER
        for new in (9.5, None):  # (a) changed live line, (b) book has no market
            env.state[key] = new
            assert _snap(gen(env), *cols) == first
        env.state[key] = 9.5
        env.state["boom"] = True  # (c) projector fails on rerun
        assert _snap(gen(env), *cols) == first
        assert _snap(gen(env, games=()), *cols) == first  # game missing from feed

    def test_prestart_no_line_keeps_previous_line(self, env, gen, cols, key):
        first = gen(env)
        line, rec = getattr(first[0], cols[0]), first[0].betting_recommendation
        env.state[key] = None
        rows = gen(env)
        assert len(rows) == 1
        assert getattr(rows[0], cols[0]) == line
        assert rows[0].betting_recommendation == rec

    def test_prestart_updates_line_and_failed_game_keeps_old_rows(
        self, env, gen, cols, key
    ):
        gen(env)
        env.state[key] = 3.5
        assert getattr(gen(env)[0], cols[0]) == 3.5
        env.state["boom"] = True  # run aborts per-game: nothing deleted
        rows = gen(env)
        assert len(rows) == 1 and getattr(rows[0], cols[0]) == 3.5


# ---- goalies ----
def _slot(goalie_id=1, name="A. Goalie", predict=True):
    return GoalieStarterContext(
        game_id=1,
        game_date=D,
        game_time=None,
        is_home=True,
        team_id=23,
        team_name="Vancouver",
        opponent_team_id=3,
        opponent_team_name="New York",
        goalie_id=goalie_id,
        goalie_name=name,
        starter_confirmed=True,
        confidence=95.0,
        should_predict=predict,
        prediction_skipped_reason=None if predict else "no_db_goalie",
        method="confirmed",
        source="espn",
        full_name=name,
    )


@pytest.fixture
def goalie(env, monkeypatch):
    monkeypatch.setattr(
        dp,
        "predict_goalie_saves",
        lambda **kw: {
            "predicted_saves": 27.0,
            "predicted_shots_against": 29.0,
            "predicted_save_pct": 0.91,
            "confidence": 80.0,
        },
    )
    monkeypatch.setattr(dp, "get_goalie_saves_odds_for_event", lambda *a, **k: {})
    box = {"line": 24.5}

    def go(slot):
        monkeypatch.setattr(
            dp,
            "get_goalie_saves_odds_for_event",
            lambda *a, **k: (
                {} if box["line"] is None else {slot.full_name: {"line": box["line"]}}
            ),
        )
        monkeypatch.setattr(
            dp,
            "build_slate_starter_context",
            lambda games: SlateStarterSummary.from_slots([slot] if games else []),
        )
        dp.generate_goalie_predictions([GAME], EVENTS)
        return env.session.query(NHLGoaliePredictions).order_by("id").all()

    go.box = box
    return go


GCOLS = ("goalie_id", "saves_line", "betting_recommendation", "was_scratch")


def test_goalie_started_game_is_frozen(env, goalie):
    first = _snap(goalie(_slot()), *GCOLS)
    env.state["now"] = AFTER
    goalie.box["line"] = 30.5  # (a) changed line
    assert _snap(goalie(_slot()), *GCOLS) == first
    goalie.box["line"] = None  # (b) no line
    assert _snap(goalie(_slot()), *GCOLS) == first
    # (c) starter changed / old starter ruled out after the start: row stays as shown
    assert _snap(goalie(_slot(2, "B. Goalie")), *GCOLS) == first
    assert _snap(goalie(_slot(2, "B. Goalie", predict=False)), *GCOLS) == first


def test_goalie_scratch_before_start_keeps_flagged_row(env, goalie):
    goalie(_slot())
    rows = goalie(_slot(2, "B. Goalie"))
    assert [(r.goalie_id, r.was_scratch) for r in rows] == [(1, True), (2, False)]
    assert rows[0].saves_line == 24.5 and rows[0].betting_recommendation


def test_goalie_scratch_unpredictable_replacement_flags_not_deletes(env, goalie):
    goalie(_slot())
    rows = goalie(_slot(2, "B. Goalie", predict=False))
    assert [(r.goalie_id, r.was_scratch) for r in rows] == [(1, True)]


def test_goalie_switching_back_revives_original_row(env, goalie):
    goalie(_slot())
    goalie(_slot(2, "B. Goalie"))
    rows = goalie(_slot())
    assert [(r.goalie_id, r.was_scratch) for r in rows] == [(1, False), (2, True)]
