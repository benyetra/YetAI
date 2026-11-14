"""Tests for nhl_accuracy_service: daily tiles, window overview, per-row results.

Verifies plumbing of the three projected NHL markets (goalies, player shots,
team totals) into the unified buckets shape, and that the window rollup keys
actuals by (id, game_date) rather than by id alone.
"""

from __future__ import annotations

from datetime import date
from itertools import count
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import nhl_accuracy_service as svc

_ids = count(1)
D1, D2, D3 = date(2026, 11, 1), date(2026, 11, 3), date(2026, 11, 5)


def _mock_db(rows_by_model):
    db = MagicMock()

    def side_effect(model):
        result = MagicMock()
        result.filter.return_value.all.return_value = rows_by_model.get(
            model.__name__, []
        )
        return result

    db.query.side_effect = side_effect
    return db


def _goalie_p(d, *, gid=42, saves=28.0, line=27.5, rec="OVER 27.5", pid=None):
    return SimpleNamespace(
        id=pid or next(_ids),
        game_date=d,
        goalie_id=gid,
        predicted_saves=saves,
        saves_line=line,
        betting_recommendation=rec,
        was_scratch=False,
    )


def _goalie_a(d, saves, *, gid=42):
    return SimpleNamespace(goalie_id=gid, game_date=d, actual_saves=saves)


def _player_p(d, *, pid_=99, shots=3.5, line=2.5, rec="OVER 2.5", pid=None):
    return SimpleNamespace(
        id=pid or next(_ids),
        game_date=d,
        player_id=pid_,
        predicted_shots=shots,
        shots_line=line,
        betting_recommendation=rec,
    )


def _player_a(d, shots, *, pid_=99):
    return SimpleNamespace(player_id=pid_, game_date=d, actual_shots=shots)


def _totals_p(d, *, home=2, away=1, line=5.5, rec="OVER 5.5", pid=None):
    return SimpleNamespace(
        id=pid or next(_ids),
        game_date=d,
        home_team_id=home,
        away_team_id=away,
        home_team_name="New York",
        away_team_name="Boston",
        predicted_total_goals=6.0,
        draftkings_ou_line=line,
        betting_recommendation=rec,
    )


def _totals_a(d, total, *, home=2, away=1):
    return SimpleNamespace(
        game_date=d,
        home_team_id=home,
        away_team_id=away,
        home_team_name="",  # what the old collector stored
        away_team_name="",
        actual_total_goals=total,
        actual_home_goals=total - 2,
        actual_away_goals=2,
    )


def test_returns_six_nhl_buckets_in_order():
    """Goalies + player shots + team totals, each O/U then MAE (no team shots)."""
    today = date(2026, 5, 23)
    db = _mock_db(
        {
            "NHLGoaliePredictions": [_goalie_p(today)],
            "NHLGoalieActuals": [_goalie_a(today, 30)],
            "NHLPlayerShotsPredictions": [_player_p(today)],
            "NHLPlayerShotsActuals": [_player_a(today, 4)],
            "NHLTeamTotalsPredictions": [_totals_p(today)],
            "NHLTeamTotalsActuals": [_totals_a(today, 6)],
        }
    )
    out = svc.daily_accuracy(db, target_date=today)
    keys = [b["key"] for b in out["buckets"]]
    assert keys == [
        "goalie_saves_ou",
        "goalie_saves_mae",
        "player_shots_ou",
        "player_shots_mae",
        "team_totals_ou",
        "team_totals_mae",
    ]
    ps = next(b for b in out["buckets"] if b["key"] == "player_shots_ou")
    assert ps["primary"] == "1/1 · 100%"
    # totals: actual 6 vs line 5.5 → over wins; joined on team ids, names blank
    tt = next(b for b in out["buckets"] if b["key"] == "team_totals_ou")
    assert tt["primary"] == "1/1 · 100%"


def test_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    # All 6 buckets still emitted (with 0/0 entries); UI hides via `available`.
    assert len(out["buckets"]) == 6


def test_pass_recommendation_drops_row_from_ou_total():
    """Predictions tagged PASS don't count for or against the O/U total
    but still contribute to MAE on the prediction type."""
    d = date(2026, 5, 23)
    db = _mock_db(
        {
            "NHLGoaliePredictions": [_goalie_p(d, rec="PASS")],
            "NHLGoalieActuals": [_goalie_a(d, 30)],
        }
    )
    out = svc.daily_accuracy(db, target_date=d)
    ou = next(b for b in out["buckets"] if b["key"] == "goalie_saves_ou")
    assert ou["primary"] == "0/0 · —"
    mae = next(b for b in out["buckets"] if b["key"] == "goalie_saves_mae")
    assert "MAE 2.00" in mae["primary"]


# ---- NHL-1: window rollup keyed by (id, game_date) --------------------------


def _window_db():
    return _mock_db(
        {
            # Player 7 OVER 2.5 on three dates, actual 4/4/0 → true 2/3.
            "NHLPlayerShotsPredictions": [_player_p(d, pid_=7) for d in (D1, D2, D3)],
            "NHLPlayerShotsActuals": [
                _player_a(d, a, pid_=7) for d, a in ((D1, 4), (D2, 4), (D3, 0))
            ],
            # Goalie 99 UNDER 25.5 on two dates, actual 20/30 → true 1/2.
            "NHLGoaliePredictions": [
                _goalie_p(d, gid=99, line=25.5, rec="UNDER 25.5") for d in (D1, D2)
            ],
            "NHLGoalieActuals": [
                _goalie_a(d, a, gid=99) for d, a in ((D1, 20), (D2, 30))
            ],
            # Same matchup twice (rematch): over 5.5 with 8 then 2 goals → 1/2.
            "NHLTeamTotalsPredictions": [_totals_p(d) for d in (D1, D3)],
            "NHLTeamTotalsActuals": [_totals_a(D1, 8), _totals_a(D3, 2)],
        }
    )


def _part(out, key):
    return next(p for p in out["parts"] if p["key"] == key)


def test_window_grades_each_prediction_against_its_own_dates_actual():
    out = svc.season_overview_diagnostics(_window_db(), start=D1, end=D3)
    p = _part(out, "player_shots_ou")
    assert (p["graded_correct"], p["graded_total"]) == (2, 3)
    g = _part(out, "goalie_saves_ou")
    assert (g["graded_correct"], g["graded_total"]) == (1, 2)
    t = _part(out, "team_totals_ou")
    assert (t["graded_correct"], t["graded_total"]) == (1, 2)


def test_window_overview_markets_and_total():
    out = svc.season_overview(_window_db(), start=D1, end=D3)
    assert out["graded_count"] == 7
    assert {m["market"]: (m["correct"], m["graded"]) for m in out["markets"]} == {
        "Goalie saves O/U": (1, 2),
        "Player shots O/U": (2, 3),
        "Team totals O/U": (1, 2),
    }


def test_diagnostics_has_no_team_shots_part():
    out = svc.season_overview_diagnostics(_window_db(), start=D1, end=D3)
    assert [p["key"] for p in out["parts"]] == [
        "goalie_saves_ou",
        "player_shots_ou",
        "team_totals_ou",
    ]


# ---- NHL-7: duplicate prediction rows count once ----------------------------


def test_duplicate_prediction_rows_are_not_double_counted():
    db = _mock_db(
        {
            "NHLPlayerShotsPredictions": [
                _player_p(D1, pid_=7, pid=1),
                _player_p(D1, pid_=7, pid=2),
            ],
            "NHLPlayerShotsActuals": [_player_a(D1, 4, pid_=7)],
        }
    )
    p = _part(svc.season_overview_diagnostics(db, start=D1, end=D1), "player_shots_ou")
    assert p["graded_total"] == 1


# ---- H-4: per-row results agree with the tile --------------------------------


def test_past_row_results_agree_with_daily_tile():
    hit, miss, push, dnp = (next(_ids) for _ in range(4))
    db = _mock_db(
        {
            "NHLPlayerShotsPredictions": [
                _player_p(D1, pid_=1, pid=hit),
                _player_p(D1, pid_=2, pid=miss),
                _player_p(D1, pid_=3, pid=push),
                _player_p(D1, pid_=4, pid=dnp),
            ],
            "NHLPlayerShotsActuals": [
                _player_a(D1, 4, pid_=1),
                _player_a(D1, 1, pid_=2),
                _player_a(D1, 2.5, pid_=3),
            ],
            "NHLTeamTotalsPredictions": [_totals_p(D1, pid=500)],
            "NHLTeamTotalsActuals": [_totals_a(D1, 8)],
        }
    )
    rows = svc.past_row_results(db, target_date=D1)
    shots = rows["player_shots"]
    assert {i: shots[i]["result"] for i in shots} == {
        hit: "hit",
        miss: "miss",
        push: "push",
        dnp: "dnp",
    }
    assert shots[hit]["actual"] == 4
    tile = next(
        b
        for b in svc.daily_accuracy(db, target_date=D1)["buckets"]
        if b["key"] == "player_shots_ou"
    )
    assert tile["primary"].startswith("1/2")  # one hit, one miss; push/dnp excluded
    tot = rows["team_totals"][500]
    assert tot["result"] == "hit"
    assert tot["actual_total_goals"] == 8
    assert tot["actual_home_score"] == 6 and tot["actual_away_score"] == 2
    assert tot["recommendation_correct"] is True
    assert rows["goalie_predictions"] == {}
