"""Receiving yards: p_over call, slate-week label, current-week grading, repair."""

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.predictions_models import RecvYdsActuals, RecvYdsPredictions
from app.services.etl.nfl import collect_recv_yds_actuals as grader
from app.services.etl.nfl import repair_recv_week_2026_11_10 as repair
from app.services.etl.nfl.recv_yds_betting import (
    attach_recv_betting,
    generate_betting_recommendation,
)
from app.services.etl.nfl import recv_yds_model
from app.services.etl.nfl.recv_yds_model import p_over
from app.services.etl.nfl.recv_yds_usage import (
    open_slate_week,
    schedule_by_team_for_week,
)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[RecvYdsPredictions.__table__, RecvYdsActuals.__table__]
    )
    return sessionmaker(bind=engine)()


def test_p_over_is_below_half_when_mean_equals_line():
    assert p_over(60.0, 60.0) < 0.5


def test_mean_above_line_but_p_over_below_half_gives_no_over():
    # Mean 66 vs line 60 is +10% (the old rule called an OVER): skew keeps P(over) < 0.5.
    assert p_over(66.0, 60.0) < 0.5
    rec = generate_betting_recommendation(66.0, 60.0, 0.80)
    assert rec["recommendation"] != "OVER"
    assert rec["p_over"] < 0.5


def test_under_called_when_mean_far_below_line_and_price_is_used(monkeypatch):
    monkeypatch.setattr(recv_yds_model, "RECV_CV_FITTED", True)
    rec = generate_betting_recommendation(30.0, 60.0, 0.80, -110, -110)
    assert rec["recommendation"] == "UNDER"
    # A very short under price raises the breakeven past the model's edge.
    short = generate_betting_recommendation(52.0, 60.0, 0.80, 100, -400)
    assert short["recommendation"] == "PASS"


def test_attach_stores_p_over():
    lines = {
        "FD": {
            "over": {"line": 60.0, "odds": -110},
            "under": {"line": 60.0, "odds": -110},
        }
    }
    out = attach_recv_betting(
        model_yards=80.0, confidence_score=0.8, player_lines=lines, anchor_alpha=0.25
    )
    assert 0 < out["p_over"] < 1


def _lines(line, over=-110, under=-110):
    return {
        "FD": {
            "over": {"line": line, "odds": over},
            "under": {"line": line, "odds": under},
        }
    }


def test_model_mean_equal_to_line_is_not_an_over():
    out = attach_recv_betting(
        model_yards=60.0, confidence_score=0.8, player_lines=_lines(60.0)
    )
    assert out["p_over"] < 0.5
    assert out["betting_recommendation"] != "OVER"


def test_published_just_under_line_with_high_model_mean_is_not_auto_under():
    # model 78 vs line 60: published = 0.25*78 + 0.75*60 = 64.5 (above); use a
    # line the anchor drags under: model 1.3x line still gives P(over) ~ 0.5+.
    line = 60.0
    out = attach_recv_betting(
        model_yards=line * 1.3,
        confidence_score=0.8,
        player_lines=_lines(line),
        anchor_alpha=0.0,
    )
    assert out["predicted_receiving_yards"] <= line  # published at/under the line
    assert out["p_over"] > 0.5
    assert out["betting_recommendation"] != "UNDER"


def test_board_with_median_at_line_has_no_systematic_side():
    # Gamma median ~ 0.77 x mean at CV 0.85, so mean = line / 0.77 puts the median on the line.
    calls = []
    for line in (25.5, 35.5, 45.5, 55.5, 65.5, 75.5):
        out = attach_recv_betting(
            model_yards=line / 0.77, confidence_score=0.8, player_lines=_lines(line)
        )
        assert abs(out["p_over"] - 0.5) < 0.05
        calls.append(out["betting_recommendation"])
    assert set(calls) == {"PASS"}


SCHEDULE = [
    {
        "week": 9,
        "game_type": "REG",
        "home_team": "A",
        "away_team": "B",
        "gameday": "2026-11-08",
        "gametime": "13:00",
    },
    {
        "week": 10,
        "game_type": "REG",
        "home_team": "A",
        "away_team": "C",
        "gameday": "2026-11-15",
        "gametime": "13:00",
    },
]


def test_slate_week_is_next_week_when_current_is_played():
    # Tuesday 11-10: calendar week is 9 (played); the lines on offer are week 10.
    assert open_slate_week(SCHEDULE, week=9, now=datetime(2026, 11, 10, 9)) == 10
    assert open_slate_week(SCHEDULE, week=9, now=datetime(2026, 11, 8, 9)) == 9


def test_started_game_is_never_on_the_slate():
    out = schedule_by_team_for_week(SCHEDULE, week=10, now=datetime(2026, 11, 15, 14))
    assert out == {}  # kicked off: row is frozen, projector skips the player


def test_grader_skips_games_not_over_and_grades_both_weeks():
    session = _session()
    for wk, day in ((9, date(2020, 1, 1)), (10, date(2999, 1, 1))):
        session.add(
            RecvYdsPredictions(
                season=2026,
                week=wk,
                game_date=day,
                player_id="p",
                player_name="P",
                position="WR",
                team_name="T",
                opponent_team_name="O",
                predicted_receiving_yards=50.0,
                ou_line=55.0,
            )
        )
    session.flush()
    stats = [{"player_id": "p", "receiving_yards": 70, "receptions": 5, "targets": 8}]
    assert (
        grader.collect_for_week(session, season=2026, week=10, weekly_stats=stats) == 0
    )
    assert (
        grader.collect_for_week(session, season=2026, week=9, weekly_stats=stats) == 1
    )
    # Idempotent re-run.
    assert (
        grader.collect_for_week(session, season=2026, week=9, weekly_stats=stats) == 1
    )
    assert session.query(RecvYdsActuals).count() == 1


def test_run_grades_current_week_as_well(monkeypatch):
    from unittest.mock import MagicMock

    from app.services.etl.nfl import _db, nfl_common, recv_yds_usage

    weeks = []
    monkeypatch.setattr(
        grader,
        "collect_for_week",
        lambda s, *, season, week, weekly_stats: weeks.append(week) or 0,
    )
    monkeypatch.setattr(_db, "init_session", lambda: None)
    monkeypatch.setattr(_db, "close_session", lambda: None)
    monkeypatch.setattr(_db, "db_session", MagicMock())
    monkeypatch.setattr(nfl_common, "get_nfl_season", lambda: 2026)
    monkeypatch.setattr(nfl_common, "get_current_nfl_week", lambda *a, **k: 11)
    monkeypatch.setattr(recv_yds_usage, "load_weekly_receiver_rows", lambda s: [])
    assert grader.run()["weeks"] == [10, 11]
    assert weeks == [10, 11]


def test_repair_dry_run_changes_nothing_then_apply_deletes_v1_only():
    session = _session()
    wrote = datetime(2026, 11, 10, 15)

    def pred(pid, version, created, week):
        return RecvYdsPredictions(
            season=2026,
            week=week,
            game_date=date(2026, 11, 10),
            player_id=pid,
            player_name=pid,
            position="WR",
            team_name="T",
            opponent_team_name="O",
            predicted_receiving_yards=50.0,
            model_version=version,
            created_at=created,
        )

    session.add_all(
        [
            pred("a", "recv_nonml_v1", wrote, 9),
            pred("b", "recv_nonml_v2", wrote, 10),
            pred("c", "recv_nonml_v1", datetime(2026, 11, 3, 9), 9),
        ]
    )
    session.add(
        RecvYdsActuals(
            season=2026,
            week=9,
            game_date=date(2026, 11, 10),
            player_id="a",
            player_name="a",
            position="WR",
            team_name="T",
            opponent_team_name="O",
            actual_receiving_yards=70.0,
        )
    )
    session.flush()

    dry = repair.repair(session)
    assert (dry["predictions"], dry["actuals"]) == (1, 1)
    assert session.query(RecvYdsPredictions).count() == 3

    repair.repair(session, apply=True)
    left = {p.player_id for p in session.query(RecvYdsPredictions).all()}
    assert left == {"b", "c"}
    assert session.query(RecvYdsActuals).count() == 0


def test_repair_covers_the_utc_window_and_prints_ids(capsys):
    session = _session()

    def pred(pid, version, created):
        return RecvYdsPredictions(
            season=2026,
            week=9,
            game_date=date(2026, 11, 10),
            player_id=pid,
            player_name=pid,
            position="WR",
            team_name="T",
            opponent_team_name="O",
            predicted_receiving_yards=50.0,
            model_version=version,
            created_at=created,
        )

    def actual(pid):
        return RecvYdsActuals(
            season=2026,
            week=9,
            game_date=date(2026, 11, 10),
            player_id=pid,
            player_name=pid,
            position="WR",
            team_name="T",
            opponent_team_name="O",
            actual_receiving_yards=70.0,
        )

    session.add_all(
        [
            pred("noon", "recv_nonml_v1", datetime(2026, 11, 10, 15)),
            # 21:00 ET on 11-10 is 02:00 UTC on 11-11: still in the window.
            pred("late", "recv_nonml_v1", datetime(2026, 11, 11, 2)),
            # 04:00 UTC on 11-10 is 23:00 ET on 11-09: outside it.
            pred("early", "recv_nonml_v1", datetime(2026, 11, 10, 4)),
            actual("noon"),
            actual("late"),
        ]
    )
    session.flush()

    dry = repair.repair(session)
    assert (dry["predictions"], dry["actuals"]) == (2, 2)
    out = capsys.readouterr().out
    assert "noon" in out and "late" in out and "early" not in out

    repair.repair(session, apply=True)
    assert session.query(RecvYdsActuals).count() == 0
    left = {(p.player_id, p.model_version) for p in session.query(RecvYdsPredictions)}
    assert left == {("early", "recv_nonml_v1")}
